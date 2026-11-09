"""Laravel projects in analyze.py / prepare.py / coolify.py. Offline: files in tmp_path only, nothing executed."""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "deploy-app" / "scripts"
TEMPLATES = SCRIPTS.parent / "templates"
sys.path.insert(0, str(SCRIPTS))

import analyze  # noqa: E402
import coolify  # noqa: E402
import phpstack  # noqa: E402
import prepare  # noqa: E402

APP_UUID = "l" * 24

COMPOSER = {"name": "laravel/laravel", "require": {"php": "^8.3", "laravel/framework": "^13.17", "laravel/tinker": "^3.0"},
            "require-dev": {"fakerphp/faker": "^1.23"}}
LOCK = {"packages": [{"name": "laravel/framework", "version": "v13.40.0",
                      "require": {"php": "^8.3", "ext-ctype": "*", "ext-mbstring": "*", "ext-openssl": "*"}}],
        "packages-dev": [{"name": "dev/tool", "version": "1.0.0", "require": {"ext-xdebug": "*"}}]}
BOOTSTRAP = """<?php
use Illuminate\\Foundation\\Application;
return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(web: __DIR__.'/../routes/web.php', commands: __DIR__.'/../routes/console.php', health: '/up')
    ->withMiddleware(function ($middleware): void {
        //
    })->create();
"""
DATABASE = """<?php
return ['connections' => [
    'sqlite' => [
        'driver' => 'sqlite',
        'url' => env('DB_URL'),
    ],
    'pgsql' => [
        'driver' => 'pgsql',
        'url' => env('DB_URL'),
        'host' => env('DB_HOST', '127.0.0.1'),
    ],
], 'redis' => ['default' => ['url' => env('REDIS_URL')]]];
"""
WELCOME = """<head>@if (file_exists(public_path('build/manifest.json')) || file_exists(public_path('hot')))
@vite(['resources/css/app.css', 'resources/js/app.js'])
@else <style>a { color: color-mix(in oklab, red 50%, blue); }</style> @endif</head>"""
ENV_EXAMPLE = "\n".join(f"{k}={sorted(v)[0]}" for k, v in phpstack.SKELETON_ENV.items()) + "\n"


def make(root: Path, files: dict) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(content, indent=2) if isinstance(content, dict) else content)
    return root


def laravel(root: Path, frontend: bool = True, **extra) -> Path:
    files = {"composer.json": COMPOSER, "composer.lock": LOCK, "artisan": "<?php\n", "public/index.php": "<?php\n",
             "bootstrap/app.php": BOOTSTRAP, "config/database.php": DATABASE, ".env.example": ENV_EXAMPLE,
             "resources/views/welcome.blade.php": WELCOME, "routes/web.php": "<?php\n"}
    if frontend:
        files["package.json"] = {"scripts": {"build": "vite build", "dev": "vite"},
                                 "devDependencies": {"vite": "^8.0.0", "laravel-vite-plugin": "^2.0.0"}}
        files["vite.config.js"] = "import laravel from 'laravel-vite-plugin';\nexport default {plugins: [laravel()]};\n"
    files.update(extra)
    return make(root, files)


def stack(root: Path) -> dict:
    return analyze.analyze(root)["stack"]


# ------------------------------------------------------------------ detection


def test_skeleton_is_laravel_not_a_vite_spa(tmp_path):
    r = analyze.analyze(laravel(tmp_path))
    s = r["stack"]
    assert s["framework"] == "laravel" and s["template"] == "php-laravel" and s["port"] == 8080
    assert s["php_version"] == "8.4" and s["php_extensions"] == "opcache pdo_pgsql" and s["laravel_version"] == 13
    assert s["frontend"] and s["node_version"] == "22" and s["verify_expect"] == "https://{domain}/build/"
    assert s["check_routes"] == ["/up"] and s["trust_proxies"] == "generated"
    assert s["generated_env"] == ["APP_KEY:laravel"] and s["url_env"] == ["APP_URL"] and s["db_env_key"] == "DB_URL"
    assert r["deployable"] and r["databases"] == ["postgresql"] and r["warnings"] == []
    assert r["env_vars"]["in_code"] == [] and r["env_vars"]["example"] == {}
    assert r["env_vars"]["managed"] == ["APP_KEY", "APP_URL"]


def test_no_build_script_uses_the_api_template(tmp_path):
    s = stack(laravel(tmp_path, frontend=False))
    assert s["template"] == "php-laravel-api" and "verify_expect" not in s and not s["frontend"]


def test_symfony_is_blocked_even_with_encore(tmp_path):
    make(tmp_path, {"composer.json": {"require": {"symfony/framework-bundle": "^7.0"}},
                    "package.json": {"devDependencies": {"@symfony/webpack-encore": "^5"}, "scripts": {"build": "encore"}}})
    r = analyze.analyze(tmp_path)
    assert r["stack"]["framework"] == "symfony" and not r["deployable"]


def test_plain_php_and_node_with_composer_are_unchanged(tmp_path):
    make(tmp_path / "php", {"index.php": "<?php echo 1;", "composer.json": {"require": {"monolog/monolog": "^3"}}})
    assert stack(tmp_path / "php")["template"] == "php-apache"
    make(tmp_path / "node", {"package.json": {"dependencies": {"express": "^4"}, "scripts": {"start": "node s.js"}},
                             "composer.json": {"require": {"monolog/monolog": "^3"}}})
    assert stack(tmp_path / "node")["language"] == "node"


def test_laravel_10_and_old_structure_messages(tmp_path):
    old = {**LOCK, "packages": [{"name": "laravel/framework", "version": "v10.48.0"}]}
    r = analyze.analyze(laravel(tmp_path / "a", **{"composer.lock": old}))
    assert "10 or older" in " ".join(r["blockers"])
    r = analyze.analyze(laravel(tmp_path / "b", **{"app/Http/Kernel.php": "<?php\n"}))
    assert "pre-11 application structure" in " ".join(r["blockers"])


def test_missing_artisan_is_blocked(tmp_path):
    laravel(tmp_path)
    (tmp_path / "artisan").unlink()
    assert "artisan" in " ".join(analyze.analyze(tmp_path)["blockers"])


@pytest.mark.parametrize("repos,blocked", [
    ([{"type": "composer", "url": "https://nova.laravel.com"}], True),
    ([{"type": "composer", "url": "https://user:s3cr3t-token@repo.example.org"}], True),
    ([{"type": "vcs", "url": "git@git.example.org:team/pkg.git"}], True),
    ([{"type": "vcs", "url": "https://git.example.org/team/pkg.git"}], True),
    ([{"type": "vcs", "url": "https://github.com/someone/fork"}], False),
    ([{"type": "path", "url": "../shared"}], True),
    ({"packagist.org": False}, False),
])
def test_composer_repositories(tmp_path, repos, blocked):
    r = analyze.analyze(laravel(tmp_path, **{"composer.json": {**COMPOSER, "repositories": repos}}))
    assert (not r["deployable"]) is blocked
    assert "s3cr3t-token" not in json.dumps(r)  # credentials inside a repository URL are never printed


def test_path_repository_inside_copies_everything_before_install(tmp_path):
    s = stack(laravel(tmp_path, **{"composer.json": {**COMPOSER, "repositories": [{"type": "path", "url": "packages/*"}]},
                                   "packages/shop/composer.json": {"name": "acme/shop"}}))
    assert s["composer_copy"] == "all" and s["template"] == "php-laravel"


def test_auth_json_blocks_and_is_a_sensitive_file(tmp_path):
    r = analyze.analyze(laravel(tmp_path, **{"auth.json": {"http-basic": {"nova.laravel.com": {"password": "x"}}}}))
    assert "auth.json" in " ".join(r["blockers"])
    assert any(f["file"] == "auth.json" for f in r["secrets"])


# ------------------------------------------------------------------ PHP version and extensions


@pytest.mark.parametrize("spec,platform,expected", [
    ("^8.3", None, "8.4"), ("~8.2.0", None, "8.2"), ("8.2.*", None, "8.2"), (">=8.2 <8.4", None, "8.3"),
    ("^8.5", None, "8.5"), (">=8.1", None, "8.4"), ("^8.2|^8.3", None, "8.4"), ("^8.3", "8.2.10", "8.2")])
def test_php_version(spec, platform, expected):
    composer = {"require": {"php": spec}, **({"config": {"platform": {"php": platform}}} if platform else {})}
    assert phpstack.php_version(composer) == expected


def test_extensions_from_composer_and_lock_only_runtime(tmp_path):
    lock = {**LOCK, "packages": LOCK["packages"] + [{"name": "intervention/image", "require": {"ext-gd": "*"}}]}
    composer = {**COMPOSER, "require": {**COMPOSER["require"], "ext-intl": "*", "ext-zend-opcache": "*",
                                        "ext-pdo_mysql": "*", "ext-Weird.Name": "*"}}
    r = analyze.analyze(laravel(tmp_path, **{"composer.json": composer, "composer.lock": lock}))
    assert r["stack"]["php_extensions"] == "gd intl opcache pdo_pgsql"  # no xdebug (dev), mbstring (built in), mysql
    assert "weird.name" in r["stack"]["warning_extensions"] and r["deployable"]


def test_php_85_has_opcache_built_in(tmp_path):
    s = stack(laravel(tmp_path, **{"composer.json": {**COMPOSER, "require": {**COMPOSER["require"], "php": "^8.5"}}}))
    assert s["php_version"] == "8.5" and s["php_extensions"] == "pdo_pgsql"


def test_missing_lock_is_a_warning(tmp_path):
    laravel(tmp_path)
    (tmp_path / "composer.lock").unlink()
    r = analyze.analyze(tmp_path)
    assert r["deployable"] and any("composer.lock" in w for w in r["warnings"])


# ------------------------------------------------------------------ front end


def test_unguarded_vite_without_build_is_blocked(tmp_path):
    r = analyze.analyze(laravel(tmp_path, frontend=False,
                                **{"resources/views/layouts/app.blade.php": "<head>@vite('resources/js/app.js')</head>"}))
    assert "@vite" in " ".join(r["blockers"])


def test_guarded_skeleton_welcome_without_build_is_allowed(tmp_path):
    assert analyze.analyze(laravel(tmp_path, frontend=False))["deployable"]


def test_mix_and_build_directory_are_blocked_but_css_color_mix_is_not(tmp_path):
    r = analyze.analyze(laravel(tmp_path / "a", **{"resources/views/app.blade.php": "<link href=\"{{ mix('css/app.css') }}\">"}))
    assert "Mix" in " ".join(r["blockers"])
    r = analyze.analyze(laravel(tmp_path / "b", **{"vite.config.js": "laravel({buildDirectory: 'assets'})"}))
    assert "buildDirectory" in " ".join(r["blockers"])
    assert analyze.analyze(laravel(tmp_path / "c"))["deployable"]  # WELCOME has color-mix(


def test_node_version_engines_is_a_lower_bound(tmp_path):
    pkg = {"scripts": {"build": "vite build"}, "engines": {"node": ">=18"}}
    assert stack(laravel(tmp_path / "a", **{"package.json": pkg}))["node_version"] == "22"
    assert stack(laravel(tmp_path / "b", **{".nvmrc": "20\n"}))["node_version"] == "20"


def test_health_literal_is_the_check_route(tmp_path):
    s = stack(laravel(tmp_path, **{"bootstrap/app.php": BOOTSTRAP.replace("'/up'", "'/healthz'")}))
    assert s["check_routes"] == ["/healthz"]


# ------------------------------------------------------------------ trusted proxies


def test_trust_proxies_in_bootstrap_is_the_projects(tmp_path):
    boot = BOOTSTRAP.replace("        //\n", "        $middleware->trustProxies(at: '*');\n")
    s = stack(laravel(tmp_path, **{"bootstrap/app.php": boot}))
    assert s["trust_proxies"] == "project" and "trust Coolify's proxy" in s["warning_proxies"]


def test_commented_trust_proxies_is_ignored(tmp_path):
    boot = BOOTSTRAP.replace("        //\n", "        // $middleware->trustProxies(at: '*');\n")
    assert stack(laravel(tmp_path, **{"bootstrap/app.php": boot}))["trust_proxies"] == "generated"


def test_own_and_generated_trustedproxy_files(tmp_path):
    own = stack(laravel(tmp_path / "a", **{"config/trustedproxy.php": "<?php return ['proxies' => '10.0.0.1'];"}))
    assert own["trust_proxies"] == "project"
    generated = (TEMPLATES / "laravel-trustedproxy.php.tmpl").read_text()
    assert stack(laravel(tmp_path / "b", **{"config/trustedproxy.php": generated}))["trust_proxies"] == "generated"


def test_generated_proxy_file_trusts_nothing_without_the_variable():
    text = (TEMPLATES / "laravel-trustedproxy.php.tmpl").read_text()
    assert "env('TRUSTED_PROXIES')" in text and "'*'" not in text.split("return")[1]


# ------------------------------------------------------------------ databases, Sail, login, warnings


def test_skeleton_redis_config_is_not_a_redis_blocker_but_predis_is(tmp_path):
    assert analyze.analyze(laravel(tmp_path / "a"))["databases"] == ["postgresql"]
    composer = {**COMPOSER, "require": {**COMPOSER["require"], "predis/predis": "^2"}}
    r = analyze.analyze(laravel(tmp_path / "b", **{"composer.json": composer}))
    assert "redis" in r["databases"] and not r["deployable"]


def test_redis_facade_in_app_is_a_blocker(tmp_path):
    r = analyze.analyze(laravel(tmp_path, **{"app/Services/Cache.php": "<?php use Illuminate\\Support\\Facades\\Redis;"}))
    assert "redis" in r["databases"]


def test_redis_and_mysql_in_env_example_are_warnings(tmp_path):
    env = ENV_EXAMPLE.replace("CACHE_STORE=database", "CACHE_STORE=redis").replace("DB_CONNECTION=sqlite", "DB_CONNECTION=mysql")
    r = analyze.analyze(laravel(tmp_path, **{".env.example": env,
                                             "composer.json": {**COMPOSER, "require": {**COMPOSER["require"], "ext-pdo_mysql": "*"}}}))
    assert r["deployable"] and r["databases"] == ["postgresql"]
    assert any("Redis" in w for w in r["warnings"]) and any("mysql" in w for w in r["warnings"])


def test_pgsql_connection_without_db_url_is_blocked(tmp_path):
    r = analyze.analyze(laravel(tmp_path, **{"config/database.php": DATABASE.replace(
        "'driver' => 'pgsql',\n        'url' => env('DB_URL'),", "'driver' => 'pgsql',")}))
    assert "DB_URL" in " ".join(r["blockers"])


SAIL = """services:
  laravel.test:
    image: sail-8.4/app
  mysql:
    image: mysql/mysql-server:8.0
  redis:
    image: redis:alpine
networks:
  sail:
    driver: bridge
volumes:
  sail-mysql:
    driver: local
"""


def test_sail_compose_is_ignored_with_a_warning(tmp_path):
    r = analyze.analyze(laravel(tmp_path, **{"compose.yaml": SAIL}))
    assert r["deployable"] and any("Sail" in w for w in r["warnings"])


def test_sail_with_four_space_indentation(tmp_path):
    sail4 = "\n".join(("  " + line if line.startswith("  ") else line) for line in SAIL.splitlines()) + "\n"
    assert analyze.compose_services(sail4) == ["laravel.test", "mysql", "redis"]
    r = analyze.analyze(laravel(tmp_path, **{"compose.yaml": sail4}))
    assert r["deployable"] and any("Sail" in w for w in r["warnings"])


def test_four_space_multi_service_compose_is_still_blocked(tmp_path):
    make(tmp_path, {"index.html": "<h1>x</h1>", "compose.yaml": "services:\n    web:\n        image: a\n    db:\n        image: b\n"})
    assert not analyze.analyze(tmp_path)["deployable"]


def test_compose_counts_only_services():
    assert analyze.compose_services(SAIL) == ["laravel.test", "mysql", "redis"]
    assert analyze.compose_services("services:\n  web:\n    image: x\nvolumes:\n  data:\n") == ["web"]


def test_starter_kit_with_cashier_has_login(tmp_path):
    composer = {**COMPOSER, "require": {**COMPOSER["require"], "laravel/fortify": "^1", "laravel/cashier": "^15"}}
    r = analyze.analyze(laravel(tmp_path, **{"composer.json": composer}))
    assert r["has_login_estimate"] and not any("protected access" in w for w in r["warnings"])


def test_not_deployed_parts_are_warned(tmp_path):
    composer = {**COMPOSER, "require": {**COMPOSER["require"], "laravel/reverb": "^1"}}
    pkg = {"scripts": {"build": "vite build", "build:ssr": "vite build --ssr"}}
    r = analyze.analyze(laravel(tmp_path, **{"composer.json": composer, "package.json": pkg,
                                             "app/Jobs/SendMail.php": "<?php class SendMail implements ShouldQueue {}",
                                             "routes/console.php": "<?php Schedule::command('x')->daily();",
                                             "app/Http/Upload.php": "<?php Storage::disk('public')->put('a', 'b');"}))
    text = " ".join(r["warnings"])
    for word in ("queue worker", "scheduler", "laravel/reverb", "Inertia SSR", "lost on every deploy"):
        assert word in text
    assert r["deployable"]


def test_inertia_without_ssr_script_is_not_warned(tmp_path):
    composer = {**COMPOSER, "require": {**COMPOSER["require"], "inertiajs/inertia-laravel": "^2"}}
    r = analyze.analyze(laravel(tmp_path, **{"composer.json": composer,
                                             "config/inertia.php": "<?php return ['ssr' => ['enabled' => true]];"}))
    assert not any("SSR" in w for w in r["warnings"])


# ------------------------------------------------------------------ variables


def test_only_project_variables_are_asked_and_values_never_printed(tmp_path):
    env = ENV_EXAMPLE.replace("MAIL_MAILER=log", "MAIL_MAILER=smtp-secret-value") + "STRIPE_SECRET=\n"
    r = analyze.analyze(laravel(tmp_path, **{
        ".env.example": env, "app/Http/Pay.php": "<?php $k = env('PAYMENT_TOKEN');",
        "config/services.php": "<?php return ['x' => env('ONLY_IN_CONFIG')];",
        "resources/js/app.ts": "const k = import.meta.env.VITE_STRIPE_KEY; const n = import.meta.env.VITE_APP_NAME;"}))
    assert r["env_vars"]["in_code"] == ["PAYMENT_TOKEN", "STRIPE_SECRET", "VITE_STRIPE_KEY"]
    assert r["env_vars"]["example"] == {"STRIPE_SECRET": False}
    assert any("MAIL_MAILER" in w for w in r["warnings"]) and r["env_vars"]["changed_defaults"] == ["MAIL_MAILER"]
    assert "smtp-secret-value" not in json.dumps(r)


def test_laravel_11_skeleton_keys_are_not_asked(tmp_path):
    env = ENV_EXAMPLE + "APP_TIMEZONE=UTC\nMAIL_ENCRYPTION=null\n"
    r = analyze.analyze(laravel(tmp_path, **{".env.example": env}))
    assert r["env_vars"]["in_code"] == [] and r["warnings"] == []


def test_newer_laravel_than_the_table_warns(tmp_path):
    lock = {**LOCK, "packages": [{"name": "laravel/framework", "version": "v14.0.0"}]}
    r = analyze.analyze(laravel(tmp_path, **{"composer.lock": lock}))
    assert any("skeleton table" in w for w in r["warnings"])


def test_own_dockerfile_drops_checks_but_keeps_variables(tmp_path):
    old = {**LOCK, "packages": [{"name": "laravel/framework", "version": "v10.48.0"}]}
    env = ENV_EXAMPLE.replace("DB_CONNECTION=sqlite", "DB_CONNECTION=pgsql").replace("TRUSTED", "X")
    r = analyze.analyze(laravel(tmp_path, **{"composer.lock": old, "Dockerfile": "FROM php:8.3-apache\nEXPOSE 80\n",
                                             ".env.example": env + "TRUSTED_PROXIES=*\n"}))
    assert r["deployable"] and r["stack"]["generated_env"] == ["APP_KEY:laravel"]
    assert r["stack"]["trust_proxies"] == "dockerfile" and any("trust Coolify's proxy" in w for w in r["warnings"])
    assert "TRUSTED_PROXIES" in r["env_vars"]["in_code"]  # not set by our image here


# ------------------------------------------------------------------ prepare.py


def run_prepare(root: Path, monkeypatch, capsys, *args) -> dict:
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(root), *args])
    prepare.main()
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("frontend", [True, False])
def test_templates_render(tmp_path, monkeypatch, capsys, frontend):
    out = run_prepare(laravel(tmp_path, frontend=frontend), monkeypatch, capsys)
    assert set(out["created"]) == {"Dockerfile", ".dockerignore", "config/trustedproxy.php"}
    docker = (tmp_path / "Dockerfile").read_text()
    assert "{{" not in docker and "HEALTHCHECK" in docker and "USER www-data" in docker
    assert ("FROM vendor AS assets" in docker) is frontend and ("npx-cli.js" in docker) is frontend
    assert "RUN chown -R www-data:www-data storage bootstrap/cache" in docker
    assert "install-php-extensions opcache pdo_pgsql" in docker and "COPY composer.json composer.lock* ./" in docker
    for line in docker.splitlines():  # no trailing comments on instructions other than RUN continuations
        if re.match(r"(FROM|COPY|ENV|EXPOSE|USER|WORKDIR|CMD|HEALTHCHECK)\b", line):
            assert " #" not in line, line
    ignore = (tmp_path / ".dockerignore").read_text().splitlines()
    assert {"vendor", "public/build", "bootstrap/cache/*.php", "auth.json"} <= set(ignore)


def test_plain_php_dockerignore_is_unchanged(tmp_path, monkeypatch, capsys):
    make(tmp_path, {"index.php": "<?php echo 1;"})
    run_prepare(tmp_path, monkeypatch, capsys)
    assert "vendor" not in (tmp_path / ".dockerignore").read_text().splitlines()
    assert "php:8.3-apache" in (tmp_path / "Dockerfile").read_text()


def test_reanalysis_after_prepare_keeps_the_generated_proxy_file(tmp_path, monkeypatch, capsys):
    run_prepare(laravel(tmp_path), monkeypatch, capsys)
    r = analyze.analyze(tmp_path)
    assert r["stack"]["trust_proxies"] == "generated" and not any("proxy" in w for w in r["warnings"])


def test_project_proxy_file_is_not_overwritten(tmp_path, monkeypatch, capsys):
    own = "<?php return ['proxies' => '10.0.0.1'];"
    out = run_prepare(laravel(tmp_path, **{"config/trustedproxy.php": own}), monkeypatch, capsys, "--overwrite")
    assert "config/trustedproxy.php" not in out["created"]
    assert (tmp_path / "config/trustedproxy.php").read_text() == own


@pytest.mark.parametrize("var", ["PHP_VERSION=8.4;rm", "PHP_VERSION=7.4", "PHP_EXTENSIONS=intl;rm -rf /",
                                 "PHP_EXTENSIONS=intl  gd", "COMPOSER_COPY=RUN x", "EXT_INSTALLER=latest",
                                 "COMPOSER_VERSION=2", "NODE_VERSION=22 && x"])
def test_unsafe_php_values_are_rejected(tmp_path, var):
    with pytest.raises(ValueError):
        prepare.values(analyze.analyze(laravel(tmp_path)), dict([var.split("=", 1)]))


# ------------------------------------------------------------------ coolify.py


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(coolify, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(coolify, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(coolify, "REGISTRY", tmp_path / "apps.json")
    monkeypatch.setattr(coolify.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    coolify.write_json(coolify.CONFIG, {"url": "http://coolify.test:8000", "base_domain": "example.org",
                                        "server_uuid": "srv", "github_app_uuid": "gh", "reserved_subdomains": []})
    return tmp_path


def recorder(monkeypatch, existing=(), app=None):
    sent = []

    def fake(method, path, body=None, query=None):
        if method == "GET" and path.endswith("/envs"):
            return [{"key": k, "is_preview": False} for k in existing]
        if method == "GET":
            return app if app is not None else []
        sent.append((path, body))
        return {"uuid": APP_UUID}
    monkeypatch.setattr(coolify, "api", fake)
    return sent


def test_laravel_app_key_format_never_printed(config, monkeypatch):
    sent = recorder(monkeypatch)
    r = coolify.cmd_env_generate(argparse.Namespace(app=APP_UUID, keys=["APP_KEY:laravel"]))
    assert r["env_generated"] == {"APP_KEY": "created"}
    body = sent[0][1]
    assert body["key"] == "APP_KEY" and body["value"].startswith("base64:") and body["is_shown_once"]
    assert len(base64.b64decode(body["value"][7:])) == 32 and body["value"] not in json.dumps(r)


def test_existing_app_key_is_kept(config, monkeypatch):
    sent = recorder(monkeypatch, existing=["APP_KEY"])
    r = coolify.cmd_env_generate(argparse.Namespace(app=APP_UUID, keys=["APP_KEY:laravel"]))
    assert r["env_generated"] == {"APP_KEY": "kept"} and not sent


@pytest.mark.parametrize("spec", ["APP_KEY:rails", "APP KEY", "APP_KEY:"])
def test_unknown_format_fails_before_any_call(config, monkeypatch, spec):
    sent = recorder(monkeypatch)
    if spec == "APP_KEY:":  # empty format = the default secret
        assert coolify._generated_key(spec) == ("APP_KEY", "")
        return
    with pytest.raises(coolify.Error):
        coolify.cmd_env_generate(argparse.Namespace(app=APP_UUID, keys=[spec]))
    with pytest.raises(coolify.Error):
        coolify.cmd_create_app(argparse.Namespace(env_domain=None, env_url=None, env_generate=[spec]))
    assert not sent


def test_failed_generated_key_is_reported_with_its_format(config, monkeypatch):
    def fake(method, path, body=None, query=None):
        if method == "GET":
            return []
        raise coolify.Error("HTTP 500")
    monkeypatch.setattr(coolify, "api", fake)
    r = coolify.cmd_env_generate(argparse.Namespace(app=APP_UUID, keys=["APP_KEY:laravel"]))
    assert r["env_errors"][0]["key"] == "APP_KEY:laravel" and not r["ok"]


def test_same_key_twice_is_set_once(config, monkeypatch):
    sent = recorder(monkeypatch)
    r = coolify.cmd_env_generate(argparse.Namespace(app=APP_UUID, keys=["APP_KEY:laravel", "APP_KEY"]))
    assert len(sent) == 1 and sent[0][1]["value"].startswith("base64:") and r["env_generated"] == {"APP_KEY": "created"}


def test_create_app_sets_app_url_and_key(config, monkeypatch):
    sent = recorder(monkeypatch)
    a = argparse.Namespace(project="p", repo="o/r", branch="main", port="8080", domain="shop", name="shop",
                           environment="production", cpus=None, memory=None, dockerfile=None, base_dir=None,
                           no_autodeploy=False, env_domain=None, env_url=["APP_URL"], env_generate=["APP_KEY:laravel"])
    r = coolify.cmd_create_app(a)
    envs = {b["key"]: b for p, b in sent if p.endswith("/envs")}
    assert envs["APP_URL"]["value"] == "https://shop.example.org" and not envs["APP_URL"].get("is_shown_once")
    assert envs["APP_KEY"]["value"].startswith("base64:")
    assert r["env_url"] == ["APP_URL"] and r["env_generated"] == {"APP_KEY": "created"} and r["env_errors"] == []


def test_env_url_command(config, monkeypatch):
    sent = recorder(monkeypatch, app={"fqdn": "https://shop.example.org"})
    r = coolify.cmd_env_url(argparse.Namespace(app=APP_UUID, keys=["APP_URL"]))
    assert r["env_url"] == ["APP_URL"] and sent[0][1]["value"] == "https://shop.example.org"


def test_create_postgres_env_key(config, monkeypatch):
    sent = recorder(monkeypatch)
    a = argparse.Namespace(project="p", name="shop", app="shop", app_uuid=APP_UUID, environment="production",
                           image="postgres:17-alpine", memory="512m", buildtime=False, env_key="DB_URL")
    r = coolify.cmd_create_postgres(a)
    env = [b for p, b in sent if p.endswith("/envs")][0]
    assert env["key"] == "DB_URL" and env["value"].startswith("postgres://") and r["env_key"] == "DB_URL"
    assert env["value"] not in json.dumps(r)
    with pytest.raises(coolify.Error):
        coolify.cmd_create_postgres(argparse.Namespace(**{**vars(a), "env_key": "DB URL"}))
