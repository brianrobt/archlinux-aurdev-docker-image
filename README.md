# archlinux-aurdev-docker-image

Base Docker image for building, testing, &amp; publishing Arch packages to the AUR.

## Usage

The following is a sample Dockerfile that could be used to test the `python-conda` AUR package.

```docker
FROM brianrobt/archlinux-aur-dev:latest

# Copy local AUR package files to the container
COPY --chown=builder:builder .SRCINFO PKGBUILD ./

# Install build dependencies.  Example for python-conda:
RUN yay -S --noconfirm \
  python \
  python-archspec \
  python-boltons \
  python-boto3 \
  python-botocore \
  python-conda-package-handling \
  python-conda-libmamba-solver \
  python-platformdirs \
  python-pluggy>=1.0.0 \
  python-pycosat>=0.6.3 \
  python-requests>=2.20.1 \
  python-ruamel-yaml>=0.11.14 \
  python-tqdm

# Build the package
RUN makepkg -si --noconfirm

# Test the package was installed successfully
RUN python -c "import conda; print('Package successfully installed!')"
```
