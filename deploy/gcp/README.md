# Despliegue en Google Cloud — VM e2-micro (nivel gratuito)

Mismo stack que la instalación local (web + PostgreSQL + Redis + respaldos cada hora)
más Caddy con HTTPS automático. Validado en local con los límites de memoria de esta
carpeta: todo el stack ocupa ~170 MB de RAM.

**Costo esperado:** la e2-micro y 30 GB de disco estándar entran en el nivel gratuito
sólo en `us-central1`, `us-east1` o `us-west1` (una por cuenta de facturación). Lo que
puede cobrarse es la IP pública (~USD 3–4/mes). Revisa la página de precios antes.

Cuenta sugerida: `contacto@kainet.mx`, cuenta de facturación `0168DB-DAF3FF-180F0C`
(abierta, en MXN, sin proyectos ligados al 2026-10-29).

## 1. Proyecto y facturación

```bash
gcloud config set account contacto@kainet.mx
gcloud projects create kairest-casaleones --name="KaiRest Casa Leones"
gcloud billing projects link kairest-casaleones --billing-account=0168DB-DAF3FF-180F0C
gcloud config set project kairest-casaleones
gcloud services enable compute.googleapis.com
```

## 2. IP fija, firewall y VM

```bash
gcloud compute addresses create kairest-ip --region=us-central1
gcloud compute firewall-rules create kairest-web --allow=tcp:80,tcp:443 --target-tags=kairest
gcloud compute instances create kairest \
  --zone=us-central1-a --machine-type=e2-micro \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-standard \
  --address=kairest-ip --tags=kairest \
  --metadata-from-file=startup-script=deploy/gcp/startup.sh \
  --metadata=dominio=casaleones.kainet.mx,rama=main
gcloud compute addresses describe kairest-ip --region=us-central1 --format='value(address)'
```

## 3. DNS

Registro **A** `casaleones` → la IP del paso anterior, en el DNS de `kainet.mx`.
Caddy pide el certificado en cuanto el dominio resuelve a la VM.

## 4. Esperar y abrir

La primera vez la VM instala Docker y construye la imagen: **10–15 min** en una e2-micro.
Para ver el avance:

```bash
gcloud compute ssh kairest --zone=us-central1-a --command='sudo journalctl -u google-startup-scripts -f'
```

Luego `https://casaleones.kainet.mx` → wizard (plantilla *Barbacoa y Carnitas*).

## Operación

| Tarea | Comando (dentro de la VM, en `/opt/kairest/deploy/gcp`) |
|---|---|
| Actualizar | `sudo git -C /opt/kairest pull && sudo docker compose up -d --build` |
| Ver logs | `sudo docker compose logs -f web` |
| Olvidó contraseña | `sudo docker compose exec web flask reset-password correo@ejemplo.com` |
| Respaldos | `deploy/gcp/backups/*.dump` (cada hora, 7 días). Para bajarlos: `gcloud compute scp` |

Ojo: los respaldos viven en el mismo disco de la VM. Si se borra la VM, se van con ella.
Para el piloto basta; para producción conviene copiarlos a Cloud Storage.

## Apagar para no pagar

```bash
gcloud compute instances stop kairest --zone=us-central1-a    # conserva datos
gcloud compute instances start kairest --zone=us-central1-a
```

Con la e2-micro gratuita no hace falta apagarla entre semana. Detenida, la IP fija se
sigue cobrando.
