#!/bin/sh
# PHPantom entrypoint — ensures every composer.json directory has a
# .phpantom.toml with strategy=full so cross-file navigation works
# (hover, goToDefinition, findReferences) without manual configuration.
#
# If the user has already created .phpantom.toml in their project,
# it is never overwritten.

CONFIG_CONTENT='[indexing]
strategy = "full"
'

# Find every directory that contains a composer.json (excluding vendor/)
# and create .phpantom.toml there if one does not already exist.
find "${PWD}" -name "composer.json" \
    -not -path "*/vendor/*" \
    -not -path "*/.git/*" | while read -r composer_file; do

    dir=$(dirname "$composer_file")
    config="${dir}/.phpantom.toml"

    if [ ! -f "$config" ]; then
        # Only write if the directory is writable (workspace may be :ro)
        if [ -w "$dir" ]; then
            printf '%s' "$CONFIG_CONTENT" > "$config"
        fi
    fi
done

exec phpantom_lsp "$@"
