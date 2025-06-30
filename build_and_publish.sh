#!/bin/bash

# Script to build, tag, and publish the archlinux-aur-dev Docker image
# Based on instructions in ai-instructions.md

set -e  # Exit on any error

# Configuration
DOCKER_USERNAME="brianrobt"
IMAGE_NAME="archlinux-aur-dev"
REPO_NAME="${DOCKER_USERNAME}/${IMAGE_NAME}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to get the next version number
get_next_version() {
    local current_version=$(git tag --sort=-version:refname | head -1)

    if [ -z "$current_version" ]; then
        echo "v1.0.0"
    else
        # Remove 'v' prefix if present
        current_version=${current_version#v}

        # Split version into parts
        IFS='.' read -ra VERSION_PARTS <<< "$current_version"
        major=${VERSION_PARTS[0]}
        minor=${VERSION_PARTS[1]}
        patch=${VERSION_PARTS[2]}

        # Increment patch version
        new_version=$((minor + 1))
        echo "v${major}.${new_version}.0"
    fi
}

# Function to generate commit message
generate_commit_message() {
    local version=$1
    local changes=$(git diff --name-only HEAD~1 2>/dev/null || echo "Initial release")

    if [ "$changes" = "Initial release" ]; then
        echo "feat: initial release of archlinux-aur-dev Docker image

- Base image: archlinux/archlinux:latest
- Includes AUR helpers: yay, paru
- Development tools: base-devel, cmake, ninja, rust
- Package management tools: pacman-contrib, namcap
- Python development: python-pip
- Utilities: vim, wget, tree, treeify

Closes: #1"
    else
        echo "feat: release ${version}

- Updated Docker image with latest Arch Linux packages
- Improved build environment for AUR package development
- Enhanced development toolchain

Closes: #$(($(git log --oneline | wc -l) + 1))"
    fi
}

# Main execution
main() {
    print_status "Starting build and publish process for ${IMAGE_NAME}"

    # Step 1: Build the Docker image
    print_status "Step 1: Building Docker image..."
    if docker build -t ${IMAGE_NAME} .; then
        print_success "Docker image built successfully!"
    else
        print_error "Failed to build Docker image"
        exit 1
    fi

    # Step 2: Create new version tag
    print_status "Step 2: Creating new version tag..."
    NEW_VERSION=$(get_next_version)
    print_status "New version will be: ${NEW_VERSION}"

    # Step 3: Commit changes with conventional commit message
    print_status "Step 3: Committing changes..."

    # Check if there are changes to commit
    if git diff --quiet && git diff --cached --quiet; then
        print_warning "No changes to commit - creating empty commit for version tag"
        COMMIT_MSG=$(generate_commit_message $NEW_VERSION)
        git commit --allow-empty -m "$COMMIT_MSG"
    else
        # Stage all changes
        git add .
        COMMIT_MSG=$(generate_commit_message $NEW_VERSION)
        git commit -m "$COMMIT_MSG"
    fi

    # Create the version tag
    git tag -a ${NEW_VERSION} -m "Release ${NEW_VERSION}"
    print_success "Created tag: ${NEW_VERSION}"

    # Step 4: Tag the Docker image
    print_status "Step 4: Tagging Docker image..."
    docker tag ${IMAGE_NAME}:latest ${REPO_NAME}:latest
    docker tag ${IMAGE_NAME}:latest ${REPO_NAME}:${NEW_VERSION}
    print_success "Tagged image as ${REPO_NAME}:latest and ${REPO_NAME}:${NEW_VERSION}"

    # Step 5: Push to Docker Hub
    print_status "Step 5: Publishing to Docker Hub..."
    print_warning "Make sure you're logged in to Docker Hub (docker login)"

    # Push both latest and version tags
    if docker push ${REPO_NAME}:latest; then
        print_success "Successfully pushed ${REPO_NAME}:latest"
    else
        print_error "Failed to push ${REPO_NAME}:latest"
        exit 1
    fi

    if docker push ${REPO_NAME}:${NEW_VERSION}; then
        print_success "Successfully pushed ${REPO_NAME}:${NEW_VERSION}"
    else
        print_error "Failed to push ${REPO_NAME}:${NEW_VERSION}"
        exit 1
    fi

    # Step 6: Push git tag
    print_status "Step 6: Pushing git tag..."
    if git push origin ${NEW_VERSION}; then
        print_success "Successfully pushed git tag ${NEW_VERSION}"
    else
        print_error "Failed to push git tag ${NEW_VERSION}"
        exit 1
    fi

    print_success "Build and publish process completed successfully!"
    print_status "Image available at: https://hub.docker.com/r/${REPO_NAME}"
    print_status "Version: ${NEW_VERSION}"
}

# Run main function
main "$@"