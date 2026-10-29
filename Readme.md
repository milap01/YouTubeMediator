# YouTube Mediator

A team workspace for uploading videos and coordinating their publishing to YouTube.

## Features

- Resumable video uploads using 5 MB chunks
- File size limit of 500 MB; supported formats: MP4, MOV, WebM, and MKV
- Background upload assembly and YouTube publishing with Celery
- Creator and editor accounts with invitation-based access
- Creators can view and download completed videos; editors can manage their upload sessions
- PostgreSQL metadata storage and Redis task queue
- Docker Compose services for local development

## Roles and access

**Creators** can connect a YouTube channel, view and download completed videos, and publish or retry a YouTube upload.

**Editors** can upload for creators after their access is accepted. They can manage their resumable upload sessions. Completed videos and downloads are visible only to the creator.

## Run locally

1. Install Docker Desktop and start it.
2. Copy `.env.example` to `.env`, then fill in the required local settings and YouTube OAuth credentials.
3. From the project root, start the services:

   docker compose -f infra/docker-compose.yml up --build -d

4. Open the frontend at http://localhost:5173.

To stop the services, run:

   docker compose -f infra/docker-compose.yml down

## Notes

- This setup is for local development.
- Do not commit `.env` or add secret credentials to this README.
