import { useEffect } from "react";

export function Viewer3DView() {
  useEffect(() => {
    // Asegurar que la ventana se enfoca en el iframe
    const iframe = document.querySelector("iframe");
    if (iframe) {
      iframe.focus();
    }
  }, []);

  return (
    <div style={{ width: "100%", height: "100%", display: "flex" }}>
      <iframe
        src="/v3d/"
        style={{
          width: "100%",
          height: "100%",
          border: "none",
          backgroundColor: "#06080c",
        }}
        title="3D Viewer"
      />
    </div>
  );
}
