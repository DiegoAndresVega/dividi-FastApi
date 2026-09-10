# Registro de eventos de seguridad

Las líneas de acceso de uvicorn dicen qué ruta se pidió, pero no quién. Este
registro añade lo que falta: **quién hizo qué, desde dónde y cuándo**, para
poder reconstruirlo si algún día hace falta.

## Formato

Una línea de JSON por evento, en el logger `dividi.seguridad`, por stdout. Sale
por `docker logs` mezclado con lo demás; se filtra por el nombre del logger.

```json
{"evento":"login_fallido","momento":"2026-09-10T04:12:33+00:00","ip":"81.32.x.x","user_id":"…"}
```

Campos siempre presentes: `evento`, `momento` (UTC, ISO 8601) e `ip`. `user_id`
aparece cuando se sabe quién era.

## Qué se registra

| Evento | Cuándo |
|---|---|
| `alta_de_usuario` | registro nuevo; `por_invitacion` dice si usó código |
| `login_correcto` | login válido |
| `login_fallido` | credenciales incorrectas |
| `refresh` | rotación normal del refresh token |
| `refresh_rechazado` | token inválido, caducado o revocado |
| `refresh_token_reutilizado` | **un token ya gastado reaparece: la única señal de robo que da el sistema** |
| `logout` | cierre de sesión en el servidor |
| `cambio_de_contrasena` / `..._fallido` | cambio de contraseña |
| `operacion` | cualquier POST, PATCH, PUT o DELETE fuera de `/auth/` |

`operacion` lleva `metodo`, `ruta` y `estado`. Sale de un middleware y no de
cada endpoint a propósito: hay once rutas de borrado en nueve routers, y once
llamadas copiadas a mano envejecen mal —la que se olvide al añadir el router
doce es justo la que faltará cuando haga falta reconstruir algo.

Los GET no se registran: no cambian nada y ahogarían el registro justo cuando
hay que leerlo.

## Qué NO se escribe nunca

Contraseñas, tokens, códigos de invitación y cuerpos de petición. Hay tres
capas para que siga siendo así:

1. Los eventos se construyen con campos elegidos a mano, no volcando objetos.
2. `PROHIBIDOS` en `app/security_events.py` descarta esos nombres aunque
   alguien los pase.
3. Todo pasa además por el filtro de `app/logging_config.py`.

**El email tampoco.** Un registro de intentos fallidos con el email dentro es
una lista de correos válidos para quien llegue a leer los logs. En
`login_fallido` va el `user_id` solo si la cuenta existe, lo que ya distingue
«contraseña incorrecta» de «cuenta inexistente» sin escribir el correo.

## Consultarlo

```bash
# todos los eventos de seguridad de la última semana
docker logs --since 168h dividi-api-1 2>&1 | grep '"evento"'

# solo los logins fallidos, en tabla
docker logs --since 168h dividi-api-1 2>&1 | grep '"evento":"login_fallido"' | jq -r '[.momento,.ip,.user_id//"-"]|@tsv'

# lo que hizo un usuario concreto
docker logs --since 168h dividi-api-1 2>&1 | grep '"evento"' | jq -c 'select(.user_id=="EL-UUID")'

# la señal que más importa: ¿alguien reutilizó un refresh token?
docker logs --since 168h dividi-api-1 2>&1 | grep refresh_token_reutilizado
```

## Retención

El compose fija `max-size: 20m` y `max-file: 10` en el driver `json-file`.
Sin rotación el fichero crece sin techo hasta llenar el disco, y un disco lleno
tumba la base de datos. Doscientos megas dan de sobra para la semana que hay
que poder reconstruir.

## Lo que falta

Dos cosas de este punto siguen abiertas porque dependen de una decisión, no de
código:

- **Sacar los logs de la VPS.** Hoy viven solo en la máquina, así que quien la
  comprometa puede borrarlos. Las copias de seguridad tampoco ayudan: se
  guardan en `/opt/dividi/backups`, en la misma máquina.
- **Alertar ante picos** de 401, de 429 o de altas de usuarios. Los eventos ya
  están y son fáciles de contar; falta por dónde avisar.
