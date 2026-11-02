# Deploy AIRA to OpenShift (`ai-risk`)

Builds the Docker image **on your Mac**, pushes it to the cluster image registry, and runs it in project **`ai-risk`** with a **persistent SQLite volume**.

## Prerequisites

1. **Docker Desktop** running locally  
2. **OpenShift CLI (`oc`)** installed (`brew install openshift-cli`)  
3. Access to project `ai-risk` on `ocpv2.jazz.com.pk`  
4. Network/VPN so the API and registry resolve

## One-time login

1. Open the console:  
   https://console-openshift-console.apps.ocpv2.jazz.com.pk/k8s/cluster/projects/ai-risk  
   (trust Jazz’s corporate TLS cert if prompted)
2. Top-right → **Copy login command** → paste in a terminal, e.g.

```bash
oc login --token=... --server=https://api.ocpv2.jazz.com.pk:6443
oc project ai-risk
```

## Deploy / redeploy

```bash
cd "/Users/saad/Desktop/JAZZWORLD/Jazz AI Risk Assessment"
chmod +x openshift/deploy.sh
./openshift/deploy.sh
```

The script will:

1. `docker build` the app from the repo [Dockerfile](Dockerfile)  
2. `oc registry login` + `docker push` into `ai-risk/jazz-ai-risk-assessment:latest`  
3. Apply [openshift/](openshift/) manifests (PVC, Deployment, Service, Route)  
4. Mount PVC `aira-db` at `/data` and set `DATABASE_URL=sqlite:////data/aira.db`  
5. Print the Route URL

## What stays on the cluster

| Resource | Purpose |
| --- | --- |
| `PersistentVolumeClaim/aira-db` | SQLite file survives pod restarts |
| `Secret/aira-secrets` | `JWT_SECRET` |
| `Deployment/jazz-ai-risk-assessment` | App (1 replica, Recreate strategy for RWO PVC) |
| `Service` + `Route` | HTTPS edge termination |

## Demo login (unchanged)

| Email | Password |
| --- | --- |
| ayesha.khan@jazz.example | JazzDemo-2026 |

## Notes

- Strategy is **Recreate** (not Rolling) because the SQLite PVC is `ReadWriteOnce`.  
- Render continues to use `/tmp` via its own `DATABASE_URL`; OpenShift overrides to `/data`.  
- Jazz Gemma is only reachable if the cluster can resolve/reach the AIOps host (same constraint as Render).
