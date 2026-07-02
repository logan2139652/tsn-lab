#!/usr/bin/env bash

export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
export JAVA_TOOL_OPTIONS="-Djdk.util.zip.disableZip64ExtraFieldValidation=true"

export ONOS_HOME="$HOME/onos/onos-2.7.0"
export ONOS_ROOT="$HOME/onos/onos-src-2.7.0"

export ONOS_WEB_USER=onos
export ONOS_WEB_PASS=rocks
export ONOS_SSH_USER=karaf
export ONOS_SSH_PORT=8101
export ONOS_HOST=127.0.0.1

export PIPECONF_ID=org.onosproject.pipelines.basic
