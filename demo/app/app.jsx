// app.jsx — entry point. Mounts the wired Dashboard into #root.
// (esbuild jsx:'automatic' injects the JSX runtime, so no explicit React import.)
import { createRoot } from 'react-dom/client';
import { Dashboard } from './Dashboard.jsx';

const root = document.getElementById('root');
createRoot(root).render(<Dashboard />);
