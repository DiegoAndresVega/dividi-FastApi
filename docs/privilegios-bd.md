# Privilegios en la base de datos

> La API atiende peticiones con un rol que no es dueño de ninguna tabla. Puede leer y
> escribir filas; no puede crearlas, alterarlas, vaciarlas ni borrarlas.

Antes había un único usuario, dueño de la base y superusuario, para todo: migrar y servir.
Cualquier fallo de inyección o de lógica tenía por techo un `DROP TABLE`. Ahora hay dos
roles con trabajos distintos.

| Rol | Quién lo usa | Qué puede hacer |
|---|---|---|
| `dividi` (dev: `gastos`) | el servicio `migrate`, solo durante el despliegue | todo: es el dueño de las tablas |
| `dividi_app` (dev: `gastos_app`) | el proceso de la API, siempre | `SELECT`, `INSERT`, `UPDATE`, `DELETE` y las secuencias de ids |

`dividi_app` no tiene `CREATE` en el esquema, así que no puede crear tablas; y no es dueño de
ninguna, así que `ALTER`, `DROP` y `TRUNCATE` le devuelven un error de propiedad. Tampoco
toca `alembic_version`: la versión del esquema es cosa del despliegue.

## Las migraciones ya no van en el arranque

El `CMD` del Dockerfile solo levanta uvicorn. `alembic upgrade head` corre en un servicio
aparte del compose, que termina antes de que arranque la API:

```yaml
migrate:
  build: .
  environment:
    DATABASE_URL: ${MIGRATION_DATABASE_URL}   # el dueño
  command: ["alembic", "upgrade", "head"]

api:
  depends_on:
    migrate:
      condition: service_completed_successfully
  environment:
    DATABASE_URL: ${DATABASE_URL}             # el rol sin DDL
```

Si estuvieran en el mismo proceso, la API necesitaría permisos de DDL solo para arrancar, y
los conservaría durante toda su vida. Que es justo lo que se quería evitar.

## Aplicar los permisos

`scripts/db/privilegios.sql` los deja como deben estar y `scripts/db/aplicar-privilegios.sh`
lo ejecuta y **comprueba el resultado contra la base real**: que el rol entra, que escribe
filas, y que `CREATE TABLE`, `DROP TABLE`, `TRUNCATE` y `ALTER TABLE` le son denegados.

```bash
# en el despliegue (usuario y base `dividi`)
CLAVE_APP='...' ./scripts/db/aplicar-privilegios.sh

# en el compose de desarrollo
DB_USER=gastos DB_NAME=gastos ROL_APP=gastos_app CLAVE_APP=gastos_app \
  ./scripts/db/aplicar-privilegios.sh
```

Es idempotente: repetirlo no rompe nada. Hay que ejecutarlo **como dueño de las tablas**,
porque los permisos por defecto que fija al final se aplican a lo que cree el rol que los fija.

En desarrollo no suele hacer falta: el mismo `.sql` está montado en
`/docker-entrypoint-initdb.d/`, así que un volumen nuevo ya nace con el rol creado. Sobre un
volumen que ya existía, hay que lanzarlo a mano una vez.

## Al añadir tablas

Nada que hacer. `ALTER DEFAULT PRIVILEGES` hace que las tablas y secuencias que cree la
próxima migración nazcan ya con los permisos del rol de la aplicación.

Cuidado con una sola cosa: si alguna vez se crea una tabla desde **otro** rol distinto del
que corre las migraciones, los permisos por defecto no aplican y la API verá un
«permission denied» sobre esa tabla. La solución es volver a pasar el script.

## Limitaciones conocidas

- El rol de la aplicación puede **modificar y borrar filas** de cualquier tabla: eso es lo que
  la API necesita para funcionar. Contra el borrado masivo lo que protege son las copias de
  seguridad, no los permisos (ver [restauracion.md](restauracion.md)).
- Las migraciones siguen corriendo con un rol que es superusuario. Bajarlo a dueño sin más
  atributos es posible, pero hoy el mismo rol es el que usan `pg_dump` y los scripts de copia.
