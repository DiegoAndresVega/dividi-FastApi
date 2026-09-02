-- Privilegios mínimos para el rol con el que corre la API.
--
-- La API se conecta con un rol que solo puede leer y escribir filas: no es
-- dueño de ninguna tabla, así que un DROP, un ALTER o un TRUNCATE le devuelven
-- «permission denied» aunque quien los pida sea un fallo de inyección. Crear y
-- migrar el esquema es cosa del dueño de la base, que solo se usa durante el
-- despliegue (servicio `migrate` del compose).
--
-- Es idempotente: se puede volver a aplicar tantas veces como haga falta.
--
-- Se ejecuta de dos maneras:
--   · en desarrollo, montado en /docker-entrypoint-initdb.d/ (valores por
--     defecto de abajo), al inicializar el volumen;
--   · en un despliegue ya existente, con scripts/db/aplicar-privilegios.sh,
--     que le pasa -v rol_app=... -v clave_app=...
--
-- Debe ejecutarse SIEMPRE conectado como el dueño de las tablas: los permisos
-- por defecto que fija al final se aplican a lo que cree el rol actual.

\if :{?rol_app}
\else
\set rol_app gastos_app
\endif

\if :{?clave_app}
\else
\set clave_app gastos_app
\endif

-- CREATE ROLE no admite IF NOT EXISTS; \gexec ejecuta la sentencia solo si la
-- consulta devuelve fila, es decir, si el rol todavía no existe.
SELECT format('CREATE ROLE %I LOGIN', :'rol_app')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'rol_app')\gexec

-- Explícito a propósito: si el rol ya existía con más atributos de la cuenta,
-- esta línea se los quita.
ALTER ROLE :"rol_app"
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'clave_app';

-- Nadie crea objetos en el esquema salvo su dueño.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM :"rol_app";
GRANT USAGE ON SCHEMA public TO :"rol_app";

-- Los cuatro verbos de datos y ninguno más. GRANT ALL habría añadido TRUNCATE
-- y REFERENCES, que son justo lo que se quiere fuera.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"rol_app";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"rol_app";

-- Las tablas que cree la próxima migración nacen ya con estos permisos, sin
-- tener que acordarse de volver a pasar por aquí.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"rol_app";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO :"rol_app";

-- La tabla de versiones de Alembic es del despliegue, no de la aplicación: la
-- API no la lee ni la escribe. Si la migración aún no ha corrido, no existe.
SELECT format('REVOKE ALL ON TABLE alembic_version FROM %I', :'rol_app')
 WHERE to_regclass('public.alembic_version') IS NOT NULL\gexec
