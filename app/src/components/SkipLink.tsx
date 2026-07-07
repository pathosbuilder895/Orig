export function SkipLink({ targetId = 'main' }: { targetId?: string }) {
  return (
    <a href={`#${targetId}`} className="skip-link">
      Skip to content
    </a>
  );
}
