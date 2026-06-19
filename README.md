# Repo Controller

Streamlit tool for course-run roster management, Intra user creation, GitHub repo creation, and collaborator management.

## Secrets

Create `.streamlit/secrets.toml` locally:

```toml
GITHUB_TOKEN = "..."
GITHUB_ORG = "..."

# Either provide a ready token:
INTRA_ACCESS_TOKEN = "..."

# Or provide OAuth client credentials:
INTRA_UID = "..."
INTRA_SECRET = "..."

INTRA_CAMPUS_ID = "..."
```

## Cursus Options

Edit `cursus.json` to control the cursus dropdown:

```json
[
  {
    "cursus_id": 21,
    "cursus_title": "42cursus"
  }
]
```
