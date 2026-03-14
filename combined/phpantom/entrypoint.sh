#!/bin/sh
# PHPantom entrypoint — ensures .phpantom.toml with strategy=full exists
# at the workspace root AND in every composer.json subdirectory, so that
# hover, goToDefinition, and findReferences all work out of the box.
#
# Existing .phpantom.toml files are never overwritten.

CONFIG_CONTENT='[indexing]
strategy = "full"
'

write_config_if_missing() {
    dir="$1"
    config="${dir}/.phpantom.toml"
    if [ ! -f "$config" ] && [ -w "$dir" ]; then
        printf '%s' "$CONFIG_CONTENT" > "$config"
    fi
}

# Always write at the workspace root (PHPantom reads config from here first)
write_config_if_missing "${PWD}"

# Also write in every composer.json subdirectory (subprojects / monorepos)
find "${PWD}" -name "composer.json" \
    -not -path "*/vendor/*" \
    -not -path "*/.git/*" | while read -r composer_file; do
    write_config_if_missing "$(dirname "$composer_file")"
done

exec phpantom_lsp "$@"
