#!/bin/sh
set -eu

if [ -z "${NATAPP_AUTHTOKEN:-}" ]; then
    echo "NATAPP_AUTHTOKEN is empty; tunnel disabled."
    # Keep the optional service running without triggering restart loops.
    exec sleep infinity
fi

if [ ! -x /opt/natapp/natapp ]; then
    echo "Downloading the NATAPP Linux client from natapp.cn..."
    # The official installer resolves the authenticated download URL.
    # Its output includes credentials, so never forward it to Docker logs.
    trap 'rm -f /tmp/natapp-install.sh /tmp/natapp-install.log /opt/natapp/run_natapp.sh' EXIT
    if ! wget -q -T 30 \
        "https://natapp.cn/get.sh?authtoken=${NATAPP_AUTHTOKEN}" \
        -O /tmp/natapp-install.sh; then
        echo "Could not download the NATAPP installer; retrying after restart." >&2
        exit 1
    fi
    if ! NATAPP_INSTALL_DIR=/opt/natapp sh /tmp/natapp-install.sh > /tmp/natapp-install.log 2>&1; then
        rm -f /opt/natapp/natapp
        echo "NATAPP installation failed; check token and network access to natapp.cn." >&2
        exit 1
    fi
    rm -f /tmp/natapp-install.sh /tmp/natapp-install.log /opt/natapp/run_natapp.sh
    trap - EXIT
fi

exec /opt/natapp/natapp "-authtoken=${NATAPP_AUTHTOKEN}" -log=stdout
