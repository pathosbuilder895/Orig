import { Link, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "./context/AuthContext";

const navClass = ({ isActive }: { isActive: boolean }) =>
  `text-sm font-medium px-3 py-2 rounded-lg transition-colors ${
    isActive ? "bg-ink-900 text-white" : "text-ink-700 hover:bg-paper-200/80"
  }`;

export function AppLayout() {
  const { user, signOut } = useAuth();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-paper-200 bg-white/90 backdrop-blur-md sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-8 min-w-0">
            <Link to="/" className="font-serif text-xl font-semibold text-ink-900 shrink-0">
              Original
            </Link>
            <nav className="flex items-center gap-1">
              <NavLink to="/" end className={navClass}>
                Home
              </NavLink>
              <NavLink to="/students" className={navClass}>
                Students
              </NavLink>
            </nav>
          </div>
          <div className="flex items-center gap-3 min-w-0">
            {user && (
              <span className="text-xs text-ink-700/80 truncate max-w-[160px] sm:max-w-xs" title={user.email}>
                {user.email}
              </span>
            )}
            <button
              type="button"
              onClick={() => signOut()}
              className="text-xs font-medium text-ink-700 hover:text-ink-900 border border-paper-200 rounded-lg px-3 py-1.5"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-10">
        <Outlet />
      </main>

      <footer className="border-t border-paper-200 py-8 text-center text-xs text-ink-700/55">
        Original — stylometric authorship detection
      </footer>
    </div>
  );
}
