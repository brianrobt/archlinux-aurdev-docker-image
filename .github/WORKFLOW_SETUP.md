# GitHub Actions Workflow Setup

## Required Secrets

To use the Docker build workflow, you need to configure the following secrets in your GitHub repository:

### Docker Hub Secrets
1. `DOCKERHUB_USERNAME` - Your Docker Hub username (brianrobt)
2. `DOCKERHUB_TOKEN` - Docker Hub access token (not password)

### How to Get Docker Hub Token
1. Go to Docker Hub → Account Settings → Security
2. Click "New Access Token"
3. Give it a name (e.g., "GitHub Actions")
4. Select appropriate permissions (Read, Write, Delete)
5. Copy the token and add it to GitHub secrets

### GitHub Secrets Configuration
1. Go to your repository → Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Add both `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`

## Workflow Behavior

### Automatic Versioning
- **Dockerfile changes**: Feature bump (v1.3.0 → v1.4.0)
- **No Dockerfile changes**: Patch bump (v1.3.0 → v1.3.1)

### Publishing Locations
- **Docker Hub**: `brianrobt/archlinux-aur-dev:latest` and `brianrobt/archlinux-aur-dev:vX.Y.Z`
- **GitHub Container Registry**: `ghcr.io/brianrobt/archlinux-aurdev-docker-image:latest` and versioned tags

### Supported Architectures
- linux/amd64
- linux/arm64

## Manual Trigger
The workflow can be triggered manually via the "Actions" tab → "Build and Publish Docker Image" → "Run workflow"