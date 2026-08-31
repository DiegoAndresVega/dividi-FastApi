# Copias de seguridad y restauración

> Un backup que nunca se ha restaurado no es un backup: es una suposición.
> Por eso este documento empieza por la restauración y no por la copia.

## Registro de pruebas de restauración

| Fecha | Copia probada | Duración | Resultado |
|---|---|---|---|
| 2026-08-31 | `dividi-2026-08-31_1758.tar.age` (producción) | 2 s | ✅ 16 tablas coinciden fila a fila |
| 2026-08-31 | copia sintética con 3 tiques | 2 s | ✅ tablas y tiques coinciden hash a hash |

**Próxima prueba: antes del 2026-11-30.** El propio `backup.sh` avisa en el log cuando
pasan más de 90 días desde la última.

Al terminar una prueba, anota la fecha en la VPS para que el aviso se reinicie:

```bash
date +%Y-%m-%d > /opt/dividi/backups/ultima-restauracion.txt
```

---

## Restaurar de verdad (la VPS ha muerto)

1. **Consigue la copia.** Si la VPS aún responde, están en `/opt/dividi/backups/diarias/`.
   Si no, restaura el snapshot semanal de Hostinger desde hPanel y sácalas de ahí.

2. **Descífrala** en una máquina que tenga la clave privada:

   ```bash
   age --decrypt --identity ~/.dividi-backup/clave-privada.age \
       --output copia.tar dividi-AAAA-MM-DD_HHMM.tar.age
   tar -xf copia.tar
   ```

   Dentro hay cinco ficheros: `base-de-datos.dump`, `tiques.tar.gz`, `filas.txt`
   (conteo exacto por tabla en el momento de la copia), `info.txt` y `tiques.sha256`.

3. **Levanta la base y restaura el volcado:**

   ```bash
   docker compose up -d db
   docker exec -i dividi-db-1 pg_restore -U dividi -d dividi \
       --no-owner --no-privileges < base-de-datos.dump
   ```

4. **Devuelve los tiques a su volumen:**

   ```bash
   docker run --rm -v dividi_receipts:/tiques -v "$PWD:/copia" postgres:16-alpine \
       tar -xzf /copia/tiques.tar.gz -C /tiques
   ```

5. **Comprueba que cuadra** antes de dar el servicio por recuperado: compara el conteo de
   filas contra `filas.txt` y los hashes contra `tiques.sha256`. El script de prueba
   (siguiente sección) hace exactamente esas dos comprobaciones.

## Probar la restauración (trimestral)

No toca producción: levanta un PostgreSQL vacío en Docker, restaura dentro y verifica.

```bash
# 1. baja la copia más reciente de la VPS
scp root@<vps>:/opt/dividi/backups/diarias/$(ssh root@<vps> \
    'ls -t /opt/dividi/backups/diarias | head -1') ~/.dividi-backup/copias/

# 2. restaura y verifica
./scripts/restaurar-prueba.sh ~/.dividi-backup/copias/<copia>.tar.age \
                              ~/.dividi-backup/clave-privada.age

# 3. anota la fecha
ssh root@<vps> "date +%Y-%m-%d > /opt/dividi/backups/ultima-restauracion.txt"
```

El script falla con código distinto de cero si algo no cuadra. Requiere `age` y Docker
(`brew install age`).

---

## Qué se copia y cuándo

`scripts/backup.sh`, por cron a las 04:15 cada día:

| | |
|---|---|
| Base de datos | `pg_dump -Fc` completo, validado con `pg_restore --list` antes de aceptarlo |
| Tiques | el volumen `dividi_receipts` entero, con SHA-256 de cada fichero |
| Inventario | conteo **exacto** de filas por tabla, para verificar la restauración |
| Cifrado | `age`, clave pública |
| Retención | 7 diarias · 4 semanales (lunes) · 6 mensuales (día 1) |
| Integridad | SHA-256 de cada copia en `backups/manifiesto.sha256` |

## La clave

```
~/.dividi-backup/clave-privada.age
```

**Es lo único que descifra las copias. Si se pierde, todas son ilegibles.** Guarda una copia
en el gestor de contraseñas.

La VPS solo tiene la clave **pública** (`scripts/backup-recipient.txt`): puede crear copias,
no leerlas. Quien comprometa el servidor no se lleva el histórico, y Hostinger no puede leer
los datos financieros de los usuarios en sus snapshots.

## Limitaciones conocidas

- **La copia fuera de la VPS es el snapshot de Hostinger, y es semanal.** Si el disco muere
  seis días después del último snapshot, se pierden esos seis días. Las copias diarias viven
  en el mismo disco que protegen: sirven contra un borrado accidental, no contra un fallo de
  hardware. Bajar una copia al portátil de vez en cuando reduce esa ventana, y es gratis.
- Los snapshots están en la misma cuenta de Hostinger que la VPS: si cae la cuenta, caen los dos.
