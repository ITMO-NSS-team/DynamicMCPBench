// Monochrome range slider — the studio's single slider primitive. (Geist UI's
// Slider paints a coloured value bubble, which fights the near-monochrome theme.)
export function Slider({
  value,
  min,
  max,
  step,
  onChange,
  label,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  label?: string;
}) {
  return (
    <input
      type="range"
      className="slider"
      value={value}
      min={min}
      max={max}
      step={step}
      aria-label={label}
      onChange={(e) => onChange(Number(e.target.value))}
    />
  );
}
