import React from "react";

interface HelpOverlayProps {
  onClose: () => void;
}

export function HelpOverlay({ onClose }: HelpOverlayProps) {
  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="help-modal">
        <div className="help-header">
          <h2>⌨️ Keyboard Shortcuts</h2>
          <button className="x" onClick={onClose}>×</button>
        </div>

        <div className="help-body">
          <div className="help-section">
            <h3>🎬 Playback</h3>
            <div className="shortcuts">
              <div className="shortcut">
                <span className="key">Space</span>
                <span>Play/Pause</span>
              </div>
            </div>
          </div>

          <div className="help-section">
            <h3>🎨 Drawing</h3>
            <div className="shortcuts">
              <div className="shortcut">
                <span className="key">D, B</span>
                <span>Draw mode</span>
              </div>
              <div className="shortcut">
                <span className="key">V</span>
                <span>Select mode</span>
              </div>
              <div className="shortcut">
                <span className="key">C</span>
                <span>Cut mode</span>
              </div>
              <div className="shortcut">
                <span className="key">Click (draw)</span>
                <span>Paint effect on clip</span>
              </div>
            </div>
          </div>

          <div className="help-section">
            <h3>📐 Grid & Zoom</h3>
            <div className="shortcuts">
              <div className="shortcut">
                <span className="key">Q</span>
                <span>Toggle snap</span>
              </div>
              <div className="shortcut">
                <span className="key">Ctrl+0</span>
                <span>Reset zoom</span>
              </div>
              <div className="shortcut">
                <span className="key">+, −</span>
                <span>Zoom in/out</span>
              </div>
            </div>
          </div>

          <div className="help-section">
            <h3>⏱️ Duration</h3>
            <div className="shortcuts">
              <div className="shortcut">
                <span className="key">[, ]</span>
                <span>Duration ±50ms</span>
              </div>
            </div>
          </div>

          <div className="help-section">
            <h3>📋 Editing</h3>
            <div className="shortcuts">
              <div className="shortcut">
                <span className="key">Ctrl+C</span>
                <span>Copy clip</span>
              </div>
              <div className="shortcut">
                <span className="key">Ctrl+V</span>
                <span>Paste clip</span>
              </div>
              <div className="shortcut">
                <span className="key">Ctrl+Z</span>
                <span>Undo</span>
              </div>
              <div className="shortcut">
                <span className="key">Ctrl+Shift+Z</span>
                <span>Redo</span>
              </div>
              <div className="shortcut">
                <span className="key">Delete</span>
                <span>Delete selected</span>
              </div>
            </div>
          </div>

          <div className="help-section">
            <h3>✅ Selection</h3>
            <div className="shortcuts">
              <div className="shortcut">
                <span className="key">Ctrl+Click</span>
                <span>Multi-select</span>
              </div>
              <div className="shortcut">
                <span className="key">Ctrl+A</span>
                <span>Select track clips</span>
              </div>
              <div className="shortcut">
                <span className="key">Shift+A</span>
                <span>Select all clips</span>
              </div>
            </div>
          </div>

          <div className="help-section">
            <h3>🎯 Dragging</h3>
            <div className="shortcuts">
              <div className="shortcut">
                <span className="key">Drag (H)</span>
                <span>Move clip horizontally</span>
              </div>
              <div className="shortcut">
                <span className="key">Drag (V)</span>
                <span>Move clip to track</span>
              </div>
              <div className="shortcut">
                <span className="key">Drag edge</span>
                <span>Resize clip</span>
              </div>
            </div>
          </div>
        </div>

        <div className="help-footer">
          <p>Press <span className="key">?</span> to close help</p>
        </div>
      </div>
    </div>
  );
}
