"""
src/ui/timeline/ — submódulos extraídos de timeline_editor.py (ANALYSIS hallazgo 19).

El editor Qt `timeline_editor.py` era un monolito de ~3800 LOC. Aquí se van
extrayendo piezas autocontenidas (empezando por las sin dependencia de Qt) para
reducir el archivo y poder testearlas aisladas. El grueso del split (TimelineView,
TimelineEditorWindow, paneles) es trabajo CONTINUO y queda supeditado a la retirada
de la UI Qt (ver CLAUDE.md §0 / hallazgo 11): no se hace en bloque porque Qt no es
testeable en el entorno headless (sin PyQt5) y se está jubilando.
"""
