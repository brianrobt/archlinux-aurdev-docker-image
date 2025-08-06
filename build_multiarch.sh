#!/bin/bash

# Script to build, tag, and publish the archlinux-aur-dev Docker image for multiple architectures
# Supports AMD64 and ARM64 (Apple Silicon) architectures

set -e  # Exit on any error

# Configuration
DOCKER_USERNAME="brianrobt"
IMAGE_NAME="archlinux-aur-dev"
REPO_NAME="${DOCKER_USERNAME}/${IMAGE_NAME}"
PLATFORMS="linux/amd64,linux/arm64"

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

# Function to get the next version number based on SemVer
get_next_version() {
    local current_version=$(git tag --sort=-version:refname | head -1)
    
    if [ -z "$current_version" ]; then
        echo "v1.0.0"
        return
    fi
    
    # Remove 'v' prefix if present
    current_version=${current_version#v}
    
    # Split version into parts
    IFS='.' read -ra VERSION_PARTS <<< "$current_version"
    major=${VERSION_PARTS[0]}
    minor=${VERSION_PARTS[1]}
    patch=${VERSION_PARTS[2]}
    
    # Determine version bump type based on git commits since last tag
    local commits_since_last_tag=$(git rev-list $(git describe --tags --abbrev=0)..HEAD --count 2>/dev/null || echo "0")
    
    if [ "$commits_since_last_tag" = "0" ]; then
        print_warning "No commits since last tag. Using current version: v${current_version}"
        echo "v${current_version}"
        return
    fi
    
    # Check commit messages for conventional commit types
    local feat_count=$(git log $(git describe --tags --abbrev=0)..HEAD --oneline --grep="feat:" 2>/dev/null | wc -l || echo "0")
    local breaking_count=$(git log $(git describe --tags --abbrev=0)..HEAD --oneline --grep="BREAKING CHANGE" 2>/dev/null | wc -l || echo "0")
    
    if [ "$breaking_count" -gt 0 ]; then
        # Major version bump for breaking changes
        new_major=$((major + 1))
        echo "v${new_major}.0.0"
    elif [ "$feat_count" -gt 0 ]; then
        # Minor version bump for new features
        new_minor=$((minor + 1))
        echo "v${major}.${new_minor}.0"
    else
        # Patch version bump for bug fixes and other changes
        new_patch=$((patch + 1))
        echo "v${major}.${minor}.${new_patch}"
    fi
}

# Function to check if Docker Buildx is available
check_buildx() {
    if ! docker buildx version >/dev/null 2>&1; then
        print_error "Docker Buildx is not available. Please install Docker Desktop or enable Buildx."
        exit 1
    fi
    
    # Create a builder instance if it doesn't exist
    if ! docker buildx ls | grep -q "multiarch-builder"; then
        print_status "Creating multiarch builder instance..."
        docker buildx create --name multiarch-builder --use --bootstrap
    else
        print_status "Using existing multiarch-builder instance..."
        docker buildx use multiarch-builder
    fi
}

# Function to build and push multi-architecture image
build_and_push() {
    local version=$1
    
    print_status "Building and pushing multi-architecture Docker image..."
    print_status "Platforms: ${PLATFORMS}"
    print_status "Tags: latest, ${version}"
    
    # Build and push multi-architecture image
    docker buildx build \
        --platform "${PLATFORMS}" \
        --tag "${REPO_NAME}:latest" \
        --tag "${REPO_NAME}:${version}" \
        --push \
        .
}

# Function to generate commit message
generate_commit_message() {
    local version=$1
    local changes=$(git diff --name-only HEAD~1 2>/dev/null || echo "Initial release")
    
    if [ "$changes" = "Initial release" ]; then
        echo "feat: initial multi-arch release of archlinux-aur-dev Docker image

- Base image: archlinux/archlinux:latest
- Multi-architecture support: AMD64 and ARM64
- Includes AUR helpers: yay, paru
- Development tools: base-devel, cmake, ninja, rust
- Package management tools: pacman-contrib, namcap
- Python development: python-pip
- Utilities: vim, wget, tree, treeify

Closes: #1"
    else
        echo "feat: release ${version}

- Updated multi-architecture Docker image with latest Arch Linux packages
- Improved build environment for AUR package development
- Enhanced development toolchain for AMD64 and ARM64 platforms

Closes: #$(($(git log --oneline | wc -l) + 1))"
    fi
}

# Main execution
main() {
    print_status "Starting multi-architecture build and publish process for ${IMAGE_NAME}"
    
    # Step 1: Check prerequisites
    print_status "Step 1: Checking prerequisites..."
    
    # Check if logged into Docker Hub
    if ! docker info | grep -q "Username:"; then
        print_warning "You may not be logged into Docker Hub. Please run 'docker login' if needed."
    fi
    
    # Check Docker Buildx
    check_buildx
    print_success "Prerequisites checked successfully!"
    
    # Step 2: Determine new version
    print_status "Step 2: Determining new version..."
    NEW_VERSION=$(get_next_version)
    print_status "New version will be: ${NEW_VERSION}"
    
    # Step 3: Commit changes if any exist
    print_status "Step 3: Checking for changes to commit..."
    
    if ! git diff --quiet || ! git diff --cached --quiet; then
        print_status "Committing changes..."
        git add .
        COMMIT_MSG=$(generate_commit_message $NEW_VERSION)
        git commit -m "$COMMIT_MSG"
        print_success "Changes committed successfully!"
    else
        print_status "No changes to commit"
    fi
    
    # Step 4: Create version tag
    print_status "Step 4: Creating version tag..."
    git tag -a ${NEW_VERSION} -m "Release ${NEW_VERSION} - Multi-architecture build"
    print_success "Created tag: ${NEW_VERSION}"
    
    # Step 5: Build and push multi-architecture image
    print_status "Step 5: Building and pushing multi-architecture Docker image..."
    if build_and_push ${NEW_VERSION}; then
        print_success "Successfully built and pushed multi-architecture image!"
    else
        print_error "Failed to build and push multi-architecture image"
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
    
    print_success "Multi-architecture build and publish process completed successfully!"
    print_status "Image available at: https://hub.docker.com/r/${REPO_NAME}"
    print_status "Version: ${NEW_VERSION}"
    print_status "Architectures: AMD64, ARM64"
    print_status ""
    print_status "To use the image:"
    print_status "  docker run --rm -it ${REPO_NAME}:latest"
    print_status "  docker run --rm -it ${REPO_NAME}:${NEW_VERSION}"
}

# Show usage information
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Build and publish multi-architecture Docker image for archlinux-aur-dev"
    echo ""
    echo "Options:"
    echo "  -h, --help     Show this help message"
    echo "  --dry-run      Show what would be done without executing"
    echo ""
    echo "This script will:"
    echo "  1. Check prerequisites (Docker Buildx, login status)"
    echo "  2. Determine next version using SemVer rules"
    echo "  3. Commit any pending changes"
    echo "  4. Create a new Git tag"
    echo "  5. Build multi-architecture Docker image (AMD64 + ARM64)"
    echo "  6. Push to Docker Hub with 'latest' and version tags"
    echo "  7. Push the Git tag to remote repository"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            exit 0
            ;;
        --dry-run)
            print_status "DRY RUN MODE - No changes will be made"
            DRY_RUN=true
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Run main function if not in dry-run mode
if [ "$DRY_RUN" = true ]; then
    print_status "DRY RUN - Would execute multi-architecture build process"
    print_status "Current version: $(git tag --sort=-version:refname | head -1)"
    print_status "Next version would be: $(get_next_version)"
    print_status "Target platforms: ${PLATFORMS}"
else
    main "$@"
fi