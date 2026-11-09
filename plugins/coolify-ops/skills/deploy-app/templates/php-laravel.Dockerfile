# Template: Laravel 11+ on Apache (mod_php), non-root on 8080, migrations and caches on start. With the Vite front end.
# Variables: {{PHP_VERSION}} {{EXT_INSTALLER}} {{PHP_EXTENSIONS}} {{COMPOSER_VERSION}} {{COMPOSER_COPY}} {{NODE_VERSION}}
# Proxy trust comes from config/trustedproxy.php (generated) and TRUSTED_PROXIES below (Coolify's Traefik only).
FROM php:{{PHP_VERSION}}-apache AS base
COPY --from=mlocati/php-extension-installer:{{EXT_INSTALLER}} /usr/bin/install-php-extensions /usr/local/bin/
RUN install-php-extensions {{PHP_EXTENSIONS}} \
 && cp "$PHP_INI_DIR/php.ini-production" "$PHP_INI_DIR/php.ini"
ENV APACHE_DOCUMENT_ROOT=/var/www/html/public
RUN sed -ri 's!/var/www/html!${APACHE_DOCUMENT_ROOT}!g' /etc/apache2/sites-available/*.conf /etc/apache2/apache2.conf \
 && sed -ri 's/^Listen 80$/Listen 8080/' /etc/apache2/ports.conf \
 && sed -ri 's/<VirtualHost \*:80>/<VirtualHost *:8080>/' /etc/apache2/sites-available/000-default.conf \
 && printf '<IfModule mpm_prefork_module>\n StartServers 2\n MinSpareServers 1\n MaxSpareServers 3\n MaxRequestWorkers 10\n</IfModule>\n' > /etc/apache2/conf-enabled/zz-coolify-ops.conf \
 && a2enmod rewrite headers \
 && chown -R www-data:www-data /var/run/apache2 /var/lock/apache2 /var/log/apache2
WORKDIR /var/www/html

FROM base AS vendor
COPY --from=composer:{{COMPOSER_VERSION}} /usr/bin/composer /usr/bin/composer
RUN apt-get update && apt-get install -y --no-install-recommends unzip git && rm -rf /var/lib/apt/lists/*
{{COMPOSER_COPY}}
RUN composer install --no-dev --no-scripts --no-autoloader --prefer-dist --no-interaction
COPY . .
# Runs the project's post-autoload-dump scripts (package:discover): the app boots without database or APP_KEY
RUN composer dump-autoload --optimize --no-dev

# Front end: built where PHP and vendor/ exist (Wayfinder runs php artisan during the Vite build; Livewire, Flux and
# Ziggy are imported from vendor/)
FROM vendor AS assets
COPY --from=node:{{NODE_VERSION}}-slim /usr/local/bin/node /usr/local/bin/
COPY --from=node:{{NODE_VERSION}}-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && if [ -f package-lock.json ]; then npm ci; else npm install; fi \
 && npm run build

FROM base
ENV APP_ENV=production APP_DEBUG=false LOG_CHANNEL=stderr LOG_LEVEL=info DB_CONNECTION=pgsql \
    SESSION_SECURE_COOKIE=true TRUSTED_PROXIES=*
COPY --from=vendor /var/www/html ./
COPY --from=assets /var/www/html/public/build ./public/build
# Only storage/ and bootstrap/cache/ are writable by the web server
RUN chown -R www-data:www-data storage bootstrap/cache
USER www-data
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=5s --start-period=10s --retries=60 CMD ["php", "-r", "exit(@fsockopen('127.0.0.1', 8080) ? 0 : 1);"]
CMD ["sh", "-c", "php artisan migrate --force && php artisan optimize && exec apache2-foreground"]
