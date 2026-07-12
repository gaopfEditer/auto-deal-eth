import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { RadarPage } from "./pages/RadarPage";
import { PatternMonitorPage } from "./pages/PatternMonitorPage";
import "./styles/app.css";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<RadarPage />} />
        <Route path="/patterns" element={<PatternMonitorPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
