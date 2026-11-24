<p align="center">
  <img src="icon.svg" width="72" height="72" alt="Tradesea CRT">
</p>

<h1 align="center">Tradesea CRT</h1>

<p align="center">
  <strong>Candle Range Theory en tus gráficos de Tradesea, en cualquier temporalidad de 15 minutos a mensual y en tiempo real.</strong><br>
  Un userscript gratuito de <a href="https://github.com/xavieraijon/aijon-labs">AijonLabs</a>.
</p>

<p align="center">
  <img alt="versión" src="https://img.shields.io/badge/versión-1.5.0-2962FF">
  <img alt="licencia" src="https://img.shields.io/badge/licencia-MIT-089981">
  <img alt="Tampermonkey" src="https://img.shields.io/badge/Tampermonkey-compatible-00485B">
  <img alt="Violentmonkey" src="https://img.shields.io/badge/Violentmonkey-compatible-1E88E5">
</p>

<p align="center">
  <a href="https://raw.githubusercontent.com/xavieraijon/aijon-labs/main/userscripts/tradesea-crt/tradesea-crt.user.js"><strong>⬇ Instalar</strong></a>
  &nbsp;·&nbsp; <a href="README.md">Read in English</a>
  &nbsp;·&nbsp; <a href="../../CHANGELOG.md#tradesea-crt">Historial de cambios</a>
</p>

---

Tradesea no permite añadir indicadores propios. **Tradesea CRT** añade el que echan de menos muchos traders de CRT: revisa las temporalidades que elijas, de **15 minutos a mensual**, encuentra los setups válidos de Candle Range Theory y dibuja su rango como **Horizontal Rays** directamente en tus gráficos. Los mantiene al día a medida que cierran las velas.

## Características

- **Cualquier temporalidad de 15m a M**: 15m, 30m, 1H, 2H, 3H, 4H, 6H, 8H, 12H, D, W y M. Elige un rango (*desde 15m hasta D*) o márcalas una a una. Las velas se alinean a la sesión de CME tal como las pinta Tradesea.
- **Modo temporalidad activa**: sigue la temporalidad que tenga el gráfico, incluidas las que no están en la lista, como 5m o 45m.
- **En tiempo real**: recalcula cada 30 segundos y al instante cuando cambias de símbolo o de temporalidad.
- **Se limpia solo**: los setups completados o invalidados desaparecen sin que hagas nada.
- **Visual claro**: un color de línea por temporalidad, etiqueta en verde (alcista) o rojo (bajista) y línea discontinua mientras la C2 sigue abierta.
- **Dos modos**: todas las temporalidades seleccionadas, o solo la temporalidad activa del gráfico.
- **Compatible con gráficos divididos**: cada gráfico muestra los setups de su propio símbolo.
- **Interfaz ligera**: una pastilla que puedes arrastrar, con panel de ajustes en español o inglés según el idioma del navegador.
- **Privado**: sin peticiones externas, sin rastreo y sin órdenes. Todo se ejecuta en tu navegador.

## Instalación

1. Instala un gestor de userscripts:
   [Tampermonkey](https://www.tampermonkey.net/) (Chrome, Edge, Firefox, Safari) o [Violentmonkey](https://violentmonkey.github.io/) (Chrome, Edge, Firefox).
2. **Solo en Chrome / Edge**: abre los detalles de la extensión (`chrome://extensions` → Tampermonkey → *Detalles*) y activa **Permitir scripts de usuario**. En versiones antiguas, activa en su lugar el *Modo de desarrollador*. Sin este paso el script no se ejecuta.
3. Pulsa **[Instalar](https://raw.githubusercontent.com/xavieraijon/aijon-labs/main/userscripts/tradesea-crt/tradesea-crt.user.js)** y confirma en el gestor de userscripts.
4. Abre o recarga [app.tradesea.ai](https://app.tradesea.ai/trade). La pastilla **CRT** aparece abajo a la izquierda del gráfico.

Las actualizaciones son automáticas: el gestor de userscripts comprueba este repositorio e instala las versiones nuevas por ti.

## Cómo se usa

### La pastilla

| Elemento | Qué hace |
|---|---|
| ● punto | Verde = funcionando · Ámbar = temporalidad no soportada en modo *activa* · Rojo = error (pasa el ratón para ver el detalle) · Gris = desactivado |
| `CRT (todas) · 4 · 09:15` | Modo, número de setups dibujados y hora de la última actualización |
| ↻ | Recalcular ahora (también recupera rayos borrados sin querer) |
| ⚙ | Abrir los ajustes |
| `off` / `on` | Desactivar el script (borra sus rayos) o volver a activarlo |

Arrastra la pastilla por el texto para colocarla donde quieras. La posición se recuerda.

### Cómo leer los rayos

Cada setup dibuja dos rayos que empiezan en la vela C1: su **High** y su **Low**.

```
2H High (Bearish)      ← color de la etiqueta: verde = Bullish (alcista), rojo = Bearish (bajista)
2H Low (Bearish)       ← color de la línea: temporalidad · continua = C2 cerrada · discontinua = C2 en formación
```

| Temporalidad | 15m | 30m | 1H | 2H | 3H | 4H | 6H | 8H | 12H | D | W | M |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Color de línea | cian | verde claro | gris | azul | morado | naranja | marrón | verde azulado | rosa | índigo | pizarra | negro |

Las temporalidades que no están en la lista (solo en modo *activa*, por ejemplo 5m o 45m) se dibujan en gris azulado.

### Ajustes

| Ajuste | Por defecto | Descripción |
|---|---|---|
| Temporalidades | De 15m a D | Analiza las temporalidades que marques (*Desde … hasta …* marca un rango entero de golpe), o solo la activa del gráfico |
| Activos (C2 cerrada) | Sí | Setups con la C2 ya cerrada que aún no han llegado a su objetivo |
| En formación (C2 abierta) | Sí | Setups en los que la vela actual está barriendo C1 (todavía pueden fallar) |
| Nivel 50 % | No | Añade un rayo punteado en la mitad de C1, el primer objetivo habitual |
| Invalidar si una vela cierra fuera del rango | Sí | Elimina el setup cuando una vela posterior cierra fuera de C1 por el lado barrido |
| Antigüedad máx. | 30 velas | Ignora setups cuya C2 tenga más velas de antigüedad que este valor, en cada temporalidad |

Los ajustes se guardan en el navegador y se mantienen al recargar.

## Reglas de detección

Para cada par de velas consecutivas, **C1** (rango) y **C2**:

1. **Setup**: C2 supera **solo uno** de los extremos de C1 (barrido de liquidez) y cierra de nuevo **dentro** del rango de C1.
   Barre el mínimo → **Bullish** (objetivo: High de C1). Barre el máximo → **Bearish** (objetivo: Low de C1).
2. **Completado**: el precio alcanza el extremo opuesto de C1. El setup se elimina.
3. **Invalidado**: el setup se elimina si
   - el precio supera la mecha del barrido de C2, o
   - *(opcional, activado por defecto)* una vela posterior **cierra** fuera de C1 por el lado barrido.
4. Se ignoran las velas que barren los dos extremos o ninguno.

Las temporalidades intradía se construyen a partir de velas de 15 minutos o de 1 hora alineadas a la sesión CME Globex (18:00 hora de Nueva York); D y W son las propias velas de sesión de Tradesea, y M se construye a partir de ellas. Coinciden una a una con las velas de Tradesea.

## Solución de problemas

| Problema | Solución |
|---|---|
| No aparece la pastilla | Comprueba que *Permitir scripts de usuario* o el *Modo de desarrollador* estén activados (paso 2) y que el script esté habilitado en el gestor. Recarga la página. |
| Punto rojo | Pasa el ratón por la pastilla para ver el error. Si Tradesea ha cambiado su plataforma, actualiza el script o [abre una incidencia](https://github.com/xavieraijon/aijon-labs/issues). |
| Punto ámbar | Estás en modo *activa* con una temporalidad que el script no puede leer (segundos, o múltiplos como 2D). Cambia de temporalidad o de modo. |
| Demasiados rayos | Desmarca temporalidades, cambia al modo *activa* o baja la *Antigüedad máx.* |
| La pastilla no se ve | ⚙ → *Restablecer posición*, o cambia el tamaño de la ventana. |

## Limitaciones

- No admite temporalidades en segundos ni múltiplos de periodo (2D, 3W…). Las inferiores a 15m solo funcionan en modo *activa*.
- Cada temporalidad mira un histórico limitado (unos 10 días de mercado en 15m/30m, 6 semanas en las horarias y 3 años en D/W/M), más que suficiente para la *Antigüedad máx.* por defecto de 30 velas.
- Tradesea no ofrece una API pública para complementos. El script usa la interfaz interna del gráfico, así que una actualización de la plataforma puede romperlo hasta que salga una versión nueva.
- Los rayos son dibujos normales del gráfico. Si guardas tu layout, Tradesea puede conservar una copia; el script limpia y vuelve a dibujar sus propios rayos al cargar.

## Privacidad y seguridad

- **No hace peticiones de red propias.** Las velas salen del proveedor de datos que Tradesea ya usa para tu gráfico.
- **Solo lectura** respecto a tu cuenta: nunca envía, modifica ni cancela órdenes.
- Sin analíticas, sin rastreo y sin código remoto. Todo el código está en este único archivo; léelo antes de instalarlo.

## Aviso legal

Es una herramienta independiente, gratuita y de código abierto. **No tiene relación con Tradesea ni con TradingView, ni cuenta con su respaldo o soporte.** Todas las marcas pertenecen a sus propietarios.

Se ofrece **solo con fines educativos y de análisis** y **no es una recomendación de inversión**. Operar con futuros conlleva un riesgo considerable de pérdidas y no es adecuado para todo el mundo. Eres el único responsable de tus decisiones de trading. Asegúrate de que el uso de userscripts cumple las condiciones de las plataformas y prop firms que utilices.

## Licencia

[MIT](../../LICENSE) © Xavi Aijon · AijonLabs
