"""Detection of SSR frameworks and static exports in analyze.py (offline, files in tmp_path only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "deploy-app" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import analyze  # noqa: E402
import prepare  # noqa: E402
import repo  # noqa: E402

TEMPLATES = SCRIPTS.parent / "templates"


def project(root: Path, deps: dict, files: dict[str, str] | None = None, dev: dict | None = None,
            scripts: dict | None = None) -> dict:
    """Write a Node project and return the full analysis."""
    pkg = {"dependencies": deps, "devDependencies": dev or {}, "scripts": scripts or {"build": "x", "start": "y"}}
    (root / "package.json").write_text(json.dumps(pkg))
    (root / "package-lock.json").write_text("{}")
    for rel, content in (files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return analyze.analyze(root)


def stack(*args, **kwargs) -> dict:
    return project(*args, **kwargs)["stack"]


def assert_blocked(r: dict, words: str) -> None:
    assert not r["deployable"]
    assert r["stack"]["template"] is None
    assert words in r["stack"]["warning_framework"]


# ------------------------------------------------------------------ helpers


def test_strip_comments_keeps_strings():
    src = "a: 'http://x' // c1\n/* ssr: false */ b: \"//no\", c: `/*x*/`"
    out = analyze.strip_comments(src)
    assert "ssr" not in out and "c1" not in out
    assert "'http://x'" in out and '"//no"' in out and "`/*x*/`" in out


def test_top_level_ignores_nested_objects():
    text = "{ a: 1, routeRules: { '/x': { ssr: false } }, b: [ { ssr: false } ], ssr: true }"
    top = analyze.top_level(text, 0)
    assert "ssr: true" in top and "ssr: false" not in top


def test_literal_plain_and_computed():
    assert analyze.literal("out: 'dist'", "out") == (True, "dist")
    assert analyze.literal("out: path.join('a')", "out") == (True, None)
    assert analyze.literal("out: `x${y}`", "out") == (True, None)
    assert analyze.literal("layout: 'x'", "out") == (False, None)


# ------------------------------------------------------------------ Nuxt


def test_nuxt_default_is_server(tmp_path):
    s = stack(tmp_path, {"nuxt": "^4.6.0"}, {"nuxt.config.ts": "export default defineNuxtConfig({ devtools: {} })"})
    assert (s["template"], s["render"], s["build_dir"], s["port"]) == ("node-ssr", "server", ".output", 3000)
    assert s["start_cmd"] == ["node", ".output/server/index.mjs"]


def test_nuxt_top_level_ssr_false_is_spa(tmp_path):
    s = stack(tmp_path, {"nuxt": "^4.6.0"}, {"nuxt.config.ts": "export default defineNuxtConfig({ ssr: false })"},
              scripts={"build": "nuxt build"})
    assert (s["template"], s["build_dir"], s["spa"], s["spa_fallback"]) == ("spa-nginx", ".output/public", True,
                                                                           "200.html")
    assert s["build_cmd"] == "npx nuxt generate"


def test_nuxt_ssr_false_in_route_rules_stays_server(tmp_path):
    cfg = "export default defineNuxtConfig({ routeRules: { '/admin/**': { ssr: false } } })"
    s = stack(tmp_path, {"nuxt": "^4.6.0"}, {"nuxt.config.ts": cfg})
    assert s["render"] == "server"
    assert "routeRules" in s["warning_route_rules"]


def test_nuxt_commented_ssr_false_stays_server(tmp_path):
    cfg = "export default defineNuxtConfig({\n  // ssr: false,\n  /* ssr: false */\n})"
    s = stack(tmp_path, {"nuxt": "^4.6.0"}, {"nuxt.config.ts": cfg})
    assert s["render"] == "server"
    assert "warning_route_rules" not in s


def test_nuxt_generate_script_is_static_and_warns_about_server_dir(tmp_path):
    s = stack(tmp_path, {"nuxt": "^4.6.0"}, {"nuxt.config.ts": "export default defineNuxtConfig({})",
                                             "server/api/hello.ts": "export default 1"},
              scripts={"build": "nuxt generate"})
    assert (s["template"], s["spa"], s["build_cmd"]) == ("spa-nginx", False, "npm run build")
    assert "server/" in s["warning_server_dir"]


def test_nuxt_platform_preset_is_blocked(tmp_path):
    r = project(tmp_path, {"nuxt": "^4.6.0"}, scripts={"build": "NITRO_PRESET=vercel nuxt build"})
    assert_blocked(r, "vercel")


def test_nuxt_static_preset_in_config(tmp_path):
    cfg = "export default defineNuxtConfig({ nitro: { preset: 'static' } })"
    s = stack(tmp_path, {"nuxt": "^4.6.0"}, {"nuxt.config.ts": cfg}, scripts={"build": "nuxt build"})
    assert (s["template"], s["build_cmd"], s["spa"]) == ("spa-nginx", "npm run build", False)


def test_nuxt_2_is_blocked(tmp_path):
    assert_blocked(project(tmp_path, {"nuxt": "^2.17.0"}), "Nuxt 2")


def test_nuxt_latest_tag_is_current(tmp_path):
    assert stack(tmp_path, {"nuxt": "latest"})["render"] == "server"


# ------------------------------------------------------------------ Astro


def test_astro_without_adapter_is_static_multipage(tmp_path):
    s = stack(tmp_path, {"astro": "^7.4.0"}, {"astro.config.mjs": "export default defineConfig({})"})
    assert (s["template"], s["build_dir"], s["spa"]) == ("spa-nginx", "dist", False)
    assert "spa_fallback" not in s


def test_astro_without_config_is_static(tmp_path):
    assert stack(tmp_path, {"astro": "^7.4.0"})["render"] == "static"


def test_astro_node_standalone_is_server(tmp_path):
    cfg = "import node from '@astrojs/node'\nexport default defineConfig({ adapter: node({ mode: 'standalone' }) })"
    s = stack(tmp_path, {"astro": "^7.4.0", "@astrojs/node": "^11.0.0"}, {"astro.config.mjs": cfg})
    assert (s["template"], s["build_dir"], s["port"]) == ("node-ssr", "dist", 4321)
    assert s["start_cmd"] == ["node", "dist/server/entry.mjs"]


def test_astro_node_middleware_is_blocked(tmp_path):
    cfg = "export default defineConfig({ adapter: node({ mode: 'middleware' }) })"
    assert_blocked(project(tmp_path, {"astro": "^7", "@astrojs/node": "^11"}, {"astro.config.mjs": cfg}), "standalone")


def test_astro_platform_adapter_is_blocked(tmp_path):
    assert_blocked(project(tmp_path, {"astro": "^7", "@astrojs/vercel": "^9"}), "@astrojs/vercel")


def test_astro_server_output_without_adapter_is_blocked(tmp_path):
    cfg = "export default defineConfig({ output: 'server' })"
    assert_blocked(project(tmp_path, {"astro": "^7"}, {"astro.config.mjs": cfg}), "no adapter")


def test_astro_integrations_are_not_adapters(tmp_path):
    s = stack(tmp_path, {"astro": "^7", "@astrojs/mdx": "^4", "@astrojs/react": "^4"})
    assert s["render"] == "static"


# ------------------------------------------------------------------ SvelteKit


SK_NODE = "import adapter from '@sveltejs/adapter-node';\nexport default { kit: { adapter: adapter(%s) } };"
SK_STATIC = "import adapter from '@sveltejs/adapter-static';\nexport default { kit: { adapter: adapter(%s) } };"


def test_sveltekit_adapter_node_default_out(tmp_path):
    s = stack(tmp_path, {}, {"svelte.config.js": SK_NODE % ""}, dev={"@sveltejs/kit": "^3", "@sveltejs/adapter-node": "^6"})
    assert (s["template"], s["build_dir"], s["start_cmd"]) == ("node-ssr", "build", ["node", "build/index.js"])
    assert s["extra_env"] == {"PROTOCOL_HEADER": "x-forwarded-proto", "HOST_HEADER": "x-forwarded-host"}


def test_sveltekit_adapter_node_custom_out(tmp_path):
    s = stack(tmp_path, {}, {"svelte.config.js": SK_NODE % "{ out: 'server-out' }"}, dev={"@sveltejs/kit": "^3"})
    assert (s["build_dir"], s["start_cmd"]) == ("server-out", ["node", "server-out/index.js"])


def test_sveltekit_env_prefix_prefixes_keys(tmp_path):
    s = stack(tmp_path, {}, {"svelte.config.js": SK_NODE % "{ envPrefix: 'APP_' }"}, dev={"@sveltejs/kit": "^3"})
    assert s["extra_env"] == {"APP_PROTOCOL_HEADER": "x-forwarded-proto", "APP_HOST_HEADER": "x-forwarded-host",
                              "APP_PORT": "3000", "APP_HOST": "0.0.0.0"}


def test_sveltekit_adapter_static_without_fallback_is_multipage(tmp_path):
    s = stack(tmp_path, {}, {"svelte.config.js": SK_STATIC % ""}, dev={"@sveltejs/kit": "^3"})
    assert (s["template"], s["build_dir"], s["spa"]) == ("spa-nginx", "build", False)


def test_sveltekit_adapter_static_with_fallback_is_spa(tmp_path):
    cfg = SK_STATIC % "{ pages: 'public', fallback: '200.html' }"
    s = stack(tmp_path, {}, {"svelte.config.js": cfg}, dev={"@sveltejs/kit": "^3"})
    assert (s["build_dir"], s["spa"], s["spa_fallback"]) == ("public", True, "200.html")


@pytest.mark.parametrize("cfg", ["import adapter from '@sveltejs/adapter-auto';\nexport default {}", None])
def test_sveltekit_adapter_auto_or_no_config_is_blocked(tmp_path, cfg):
    files = {"svelte.config.js": cfg} if cfg else {}
    assert_blocked(project(tmp_path, {}, files, dev={"@sveltejs/kit": "^3"}), "@sveltejs/adapter-node")


def test_sveltekit_static_env_is_build_time(tmp_path):
    r = project(tmp_path, {}, {"svelte.config.js": SK_NODE % "",
                               "src/routes/+page.server.ts":
                                   "import { DB_URL, API_KEY as key } from '$env/static/private';\n"},
                dev={"@sveltejs/kit": "^3"})
    assert r["build_time_env"] == ["API_KEY", "DB_URL"]
    assert set(r["env_vars"]["in_code"]) >= {"API_KEY", "DB_URL"}
    assert any("build time" in w for w in r["warnings"])


# ------------------------------------------------------------------ Angular


def angular(root: Path, version: str, options: dict, deps: dict | None = None) -> dict:
    files = {"angular.json": json.dumps({"projects": {"web": {"architect": {"build": {
        "builder": "@angular/build:application", "options": {"outputPath": "dist/web", **options}}}}}})}
    return project(root, {"@angular/core": version, **(deps or {})}, files)


def test_angular_ssr_is_server(tmp_path):
    r = angular(tmp_path, "^19.2.0", {"server": "src/main.server.ts", "ssr": {"entry": "src/server.ts"}})
    s = r["stack"]
    assert (s["template"], s["build_dir"], s["port"]) == ("node-ssr", "dist/web", 4000)
    assert s["start_cmd"] == ["node", "dist/web/server/server.mjs"]
    assert s["runtime_env"] == {"NG_ALLOWED_HOSTS": "{domain}"}
    assert s["ssr_marker"] == "ng-server-context"
    assert "NG_TRUST_PROXY_HEADERS" in s["extra_env"]
    assert r["deployable"]


def test_angular_ssr_false_is_static(tmp_path):
    s = angular(tmp_path, "^19.2.0", {"ssr": False})["stack"]
    assert (s["template"], s["build_dir"], s["spa_fallback"]) == ("spa-nginx", "dist/web/browser", "index.html")


def test_angular_static_output_mode_uses_csr_fallback(tmp_path):
    s = angular(tmp_path, "^20.0.0", {"ssr": {"entry": "src/server.ts"}, "outputMode": "static"})["stack"]
    assert (s["template"], s["build_dir"], s["spa_fallback"]) == ("spa-nginx", "dist/web/browser", "index.csr.html")


def test_angular_allowed_hosts_in_config_needs_no_env(tmp_path):
    s = angular(tmp_path, "^19.2.0", {"ssr": {"entry": "src/server.ts"},
                                      "security": {"allowedHosts": ["example.org"]}})["stack"]
    assert s["runtime_env"] == {}


def test_angular_universal_is_blocked(tmp_path):
    r = project(tmp_path, {"@angular/core": "^16.0.0", "@nguniversal/express-engine": "^16.0.0"})
    assert_blocked(r, "@nguniversal")


@pytest.mark.parametrize("version,node", [("^21.0.0", "22"), ("^22.2.0", "24")])
def test_angular_21_and_22_node_versions(tmp_path, version, node):
    assert angular(tmp_path, version, {})["stack"]["node_version"] == node


# ------------------------------------------------------------------ React Router, Remix


def test_react_router_default_is_server(tmp_path):
    s = stack(tmp_path, {"@react-router/serve": "^8", "react-router": "^8"}, dev={"@react-router/dev": "^8", "vite": "^7"})
    assert (s["template"], s["build_dir"], s["port"]) == ("node-ssr", "build", 3000)
    assert s["start_cmd"] == ["./node_modules/.bin/react-router-serve", "build/server/index.js"]


def test_react_router_spa_mode(tmp_path):
    s = stack(tmp_path, {"react-router": "^8"}, {"react-router.config.ts": "export default { ssr: false }"},
              dev={"@react-router/dev": "^8", "vite": "^7"})
    assert (s["template"], s["build_dir"], s["spa"], s["spa_fallback"]) == ("spa-nginx", "build/client", True,
                                                                           "index.html")


def test_react_router_spa_with_prerender_uses_spa_fallback_file(tmp_path):
    cfg = "export default { ssr: false, prerender: ['/'] }"
    s = stack(tmp_path, {"react-router": "^8"}, {"react-router.config.ts": cfg}, dev={"@react-router/dev": "^8"})
    assert s["spa_fallback"] == "__spa-fallback.html"


def test_react_router_without_serve_is_blocked(tmp_path):
    r = project(tmp_path, {"react-router": "^8"}, dev={"@react-router/dev": "^8", "@react-router/serve": "^8"})
    assert_blocked(r, "@react-router/serve")


def test_remix_classic_stays_on_node_server(tmp_path):
    s = stack(tmp_path, {"@remix-run/serve": "^2"}, dev={"@remix-run/dev": "^2"},
              scripts={"build": "remix build", "start": "remix-serve ./build/index.js"})
    assert (s["framework"], s["template"]) == ("remix", "node-server")


def test_remix_vite_with_start_runs_on_node_server(tmp_path):
    s = stack(tmp_path, {"@remix-run/serve": "^2"}, dev={"@remix-run/dev": "^2", "vite": "^5"},
              scripts={"build": "remix vite:build", "start": "remix-serve ./build/server/index.js"})
    assert s["template"] == "node-server"


def test_remix_vite_without_start_is_blocked(tmp_path):
    r = project(tmp_path, {}, dev={"@remix-run/dev": "^2", "vite": "^5"}, scripts={"build": "remix vite:build"})
    assert_blocked(r, "start")


# ------------------------------------------------------------------ Next.js, meta-frameworks, regressions


def test_next_export_is_static(tmp_path):
    s = stack(tmp_path, {"next": "^16"}, {"next.config.mjs": "export default { output: 'export' }"})
    assert (s["template"], s["build_dir"], s["spa"]) == ("spa-nginx", "out", False)


def test_next_export_with_dist_dir(tmp_path):
    s = stack(tmp_path, {"next": "^16"}, {"next.config.ts": "const c = { output: 'export', distDir: 'site' }"})
    assert s["build_dir"] == "site"


def test_plain_next_unchanged(tmp_path):
    s = stack(tmp_path, {"next": "^16"}, {"next.config.ts": "export default { reactStrictMode: true }"})
    assert (s["template"], s["port"]) == ("nextjs", 3000)


@pytest.mark.parametrize("dep", ["@solidjs/start", "@builder.io/qwik-city", "vike", "@tanstack/react-start",
                                 "@analogjs/platform"])
def test_vite_meta_frameworks_are_blocked(tmp_path, dep):
    r = project(tmp_path, {dep: "^1", "@angular/core": "^20"} if "analog" in dep else {dep: "^1"}, dev={"vite": "^7"})
    assert_blocked(r, "own Dockerfile")


def test_plain_vite_react_still_spa(tmp_path):
    s = stack(tmp_path, {"react": "^19"}, dev={"vite": "^7"})
    assert (s["framework"], s["template"], s["build_dir"], s["spa_fallback"]) == ("vite", "spa-nginx", "dist",
                                                                                  "index.html")


def test_own_dockerfile_still_wins(tmp_path):
    r = project(tmp_path, {"@solidjs/start": "^1"}, {"Dockerfile": "FROM node:22\nEXPOSE 3000\n"})
    assert r["deployable"]
    assert r["stack"]["existing_dockerfile"]


# ------------------------------------------------------------------ prepare.py and templates


def render_for(analysis: dict) -> tuple[str, str | None]:
    """Rendered Dockerfile and nginx.conf (or None) for an analysis, as prepare.py would write them."""
    s = analysis["stack"]
    v = prepare.values(analysis, {})
    conf = prepare.nginx_conf(s["template"], s)
    dockerfile = prepare.render((TEMPLATES / f"{s['template']}.Dockerfile").read_text(), v)
    return dockerfile, prepare.render((TEMPLATES / conf).read_text(), v) if conf else None


def test_node_ssr_dockerfile_for_sveltekit(tmp_path):
    r = project(tmp_path, {}, {"svelte.config.js": SK_NODE % ""}, dev={"@sveltejs/kit": "^3"})
    dockerfile, conf = render_for(r)
    assert conf is None and "{{" not in dockerfile
    assert "npm ci --omit=dev --ignore-scripts" in dockerfile
    assert "COPY --from=build /app/build ./build" in dockerfile
    assert "HOST=0.0.0.0 PROTOCOL_HEADER=x-forwarded-proto HOST_HEADER=x-forwarded-host" in dockerfile
    cmd = next(line for line in dockerfile.splitlines() if line.startswith("CMD "))
    assert json.loads(cmd[4:]) == ["node", "build/index.js"]


def test_node_ssr_dockerfile_for_react_router(tmp_path):
    r = project(tmp_path, {"@react-router/serve": "^8"}, dev={"@react-router/dev": "^8"})
    dockerfile, _ = render_for(r)
    assert 'CMD ["./node_modules/.bin/react-router-serve", "build/server/index.js"]' in dockerfile
    assert "ENV NODE_ENV=production PORT=3000 HOST=0.0.0.0\n" in dockerfile


def test_spa_fallback_is_rendered(tmp_path):
    cfg = SK_STATIC % "{ fallback: '200.html' }"
    _, conf = render_for(project(tmp_path, {}, {"svelte.config.js": cfg}, dev={"@sveltejs/kit": "^3"}))
    assert "try_files $uri $uri/ /200.html;" in conf


def test_multipage_static_site_gets_static_conf(tmp_path):
    _, conf = render_for(project(tmp_path, {"astro": "^7"}))
    assert "$uri.html =404" in conf and "error_page 404 /404.html" in conf


def test_existing_spa_keeps_index_fallback(tmp_path):
    _, conf = render_for(project(tmp_path, {"react": "^19"}, dev={"vite": "^7"}))
    assert "try_files $uri $uri/ /index.html;" in conf


@pytest.mark.parametrize("stack_values", [
    {"build_dir": "../etc"}, {"build_dir": "dist; rm -rf /"}, {"build_dir": "a b"},
    {"spa_fallback": "x; }"}, {"extra_env": {"BAD KEY": "x"}}, {"extra_env": {"K": "a b"}},
    {"extra_env": {"K": "x\nRUN id"}},
])
def test_unsafe_values_from_config_are_rejected(stack_values):
    with pytest.raises(ValueError):
        prepare.values({"stack": stack_values}, {})


def test_start_cmd_override_must_be_a_list():
    with pytest.raises(ValueError):
        prepare.values({"stack": {}}, {"START_CMD": '"node x"'})


def test_unsafe_config_value_stops_prepare(tmp_path, monkeypatch, capsys):
    cfg = SK_NODE % "{ out: 'a b' }"
    project(tmp_path, {}, {"svelte.config.js": cfg}, dev={"@sveltejs/kit": "^3"})
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        prepare.main()
    assert e.value.code == 1
    assert "BUILD_DIR" in json.loads(capsys.readouterr().out)["error"]
    assert not (tmp_path / "Dockerfile").exists()


def test_build_folders_are_ignored():
    ignored = (TEMPLATES / "dockerignore").read_text().split()
    for d in (".output", ".nuxt", ".svelte-kit", ".astro", ".react-router"):
        assert d in ignored and d in analyze.IGNORED_DIRS and f"{d}/" in repo.GITIGNORE
