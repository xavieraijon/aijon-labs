# Template: plain PHP site (no framework) on Apache. Variables: {{PHP_VERSION}}
FROM php:{{PHP_VERSION}}-apache
RUN a2enmod rewrite headers
COPY . /var/www/html/
RUN chown -R www-data:www-data /var/www/html
EXPOSE 80
