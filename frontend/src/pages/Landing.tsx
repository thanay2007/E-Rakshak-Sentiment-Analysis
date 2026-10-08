import { ArrowRight, LockKeyhole } from "lucide-react";
import { Link } from "react-router-dom";
import { Logo } from "../components/Sidebar";
import "./Landing.css";

export default function Landing() {
  return (
    <main className="landing-page" aria-labelledby="landing-title">
      <div className="landing-backdrop gradient-mesh" aria-hidden="true" />
      <div className="landing-content">
        <div className="landing-emblem">
          <div className="landing-emblem-halo" aria-hidden="true" />
          <div className="landing-emblem-ring" aria-hidden="true" />
          <Logo size={88} />
        </div>
        <p className="landing-eyebrow">DIGITAL VIGILANCE</p>
        <h1 id="landing-title">E-RAKSHAK</h1>
        <p className="landing-description">
          Monitor online threats and understand public opinion.<br />
          A clearer view. A safer community.
        </p>
        <Link to="/app" className="landing-primary">
          Open command center <ArrowRight size={17} aria-hidden="true" />
        </Link>
        <p className="landing-access-note">
          <LockKeyhole size={12} aria-hidden="true" /> Authorized personnel only
        </p>
      </div>
    </main>
  );
}
