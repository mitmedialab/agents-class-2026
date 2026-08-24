import { createRoot } from "react-dom/client";
import "@class-agent/ui/styles.css";
import App from "./App.js";
import "./styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Course Agent root element is missing");
}

createRoot(root).render(<App />);
