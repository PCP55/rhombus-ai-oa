# Distributed NL-to-Regex Data Processing Platform

# Demo Video

# Setup/run instructions 
(including the async/Spark stack)

# An overview of the architecture
and the reasoning behind it,
and any notes or trade-offs.



```
rhombus-ai/
├── backend/                  <-- EVERYTHING Python/Django goes in here
│   ├── api/
│   │   ├── services/         <-- NEW: Move spark_engine.py & llm_utils.py here
│   │   ├── migrations/
│   │   ├── models.py
│   │   ├── tasks.py
│   │   └── views.py
│   ├── core/                 <-- STRICTLY settings.py, urls.py, celery.py
│   ├── media/
│   ├── .venv/
│   ├── db.sqlite3
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   ├── components/
│   └── package.json
│
├── docker-compose.yaml
├── .env
└── .gitignore
```
