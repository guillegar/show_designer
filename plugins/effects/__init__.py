# plugins/effects/__init__.py — Carpeta de plugins de efectos pixel
#
# Cada archivo .py aqui puede definir:
#
#   PLUGIN_EFFECTS = {
#       1001: MiEfecto(),
#       1002: OtroEfecto(),
#   }
#
# O simplemente subclases de Effect sin PLUGIN_EFFECTS: el loader
# las autodescubre y asigna IDs automaticamente desde PLUGIN_BASE_ID.
#
# Los efectos base (0-999) estan en effects_engine.py y NO se tocan.
