import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { NAV } from "./status";

export function useKeyboardNav() {
  const navigate = useNavigate();
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const tag = (event.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const hit = NAV.find((item) => item.key === event.key);
      if (hit) {
        event.preventDefault();
        navigate(hit.to);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);
}
