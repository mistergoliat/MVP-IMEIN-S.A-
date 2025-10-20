Pipeline ABC–XYZ — n8n + OneDrive + Python

Estructura:
- docker-compose.yml
- Dockerfile.n8n
- project/
  - abcxyz_main.py
  - config.yaml
  - requirements.txt
  - input/
  - output/csv/

Pasos:
1) docker compose build && docker compose up -d
2) n8n: http://localhost:5678 (user/pass en compose)
3) Credencial OneDrive en n8n
4) Importar n8n_workflow.json
5) Subir a OneDrive /ABCXYZ/input/: YYYY-MM_prices.xlsx, YYYY-MM_issues.xlsx, YYYY-MM_onhand.xlsx
6) Ejecutar workflow (Webhook o Cron). Resultados en /ABCXYZ/output/ y en project/output/
