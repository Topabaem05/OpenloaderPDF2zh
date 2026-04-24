import type { PropsWithChildren } from 'react';

export type NavigationItemId = 'home' | 'documents' | 'history' | 'settings';

interface WorkbenchShellProps extends PropsWithChildren {
  activeNav?: NavigationItemId;
  onNavAction?: (item: NavigationItemId) => void;
  onPrimaryAction?: () => void;
  primaryLabel?: string;
}

const navigationItems = [
  { id: 'home' as const, label: 'Home', icon: 'home' },
  { id: 'documents' as const, label: 'Documents', icon: 'description' },
  { id: 'history' as const, label: 'History', icon: 'history' },
  { id: 'settings' as const, label: 'Settings', icon: 'settings' },
];

export function WorkbenchShell({
  activeNav = 'documents',
  onNavAction,
  children,
  onPrimaryAction,
  primaryLabel = 'New Translation',
}: WorkbenchShellProps) {
  return (
    <div className="app-shell">
      <aside className="shell-sidebar">
        <div className="shell-brand">
          <h1>Alexandria</h1>
          <p>Digital Curator</p>
        </div>

        <nav className="sidebar-nav" aria-label="Primary">
          {navigationItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`sidebar-link${activeNav === item.id ? ' active' : ''}`}
              onClick={() => onNavAction?.(item.id)}
            >
              <span className="material-symbols-outlined" aria-hidden="true">
                {item.icon}
              </span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <button className="sidebar-primary" type="button" onClick={onPrimaryAction}>
          <span className="material-symbols-outlined" aria-hidden="true">
            add
          </span>
          {primaryLabel}
        </button>
      </aside>

      <div className="shell-main">{children}</div>
    </div>
  );
}
