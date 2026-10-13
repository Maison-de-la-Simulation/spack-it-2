FROM docker.io/spack/ubuntu-noble:1.2.2

# The parent image entrypoint wraps commands with Spack's docker-shell; the
# validator needs a plain entrypoint instead and sources setup-env.sh itself.
COPY validate.sh /opt/validate.sh

ENTRYPOINT ["/bin/bash", "/opt/validate.sh"]
