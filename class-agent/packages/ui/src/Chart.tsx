export type ChartType = "bar" | "line" | "area";
export type ChartDataKind = "measured" | "user-provided" | "derived";
export type ChartTone =
  | "accent"
  | "coral"
  | "secondary"
  | "success"
  | "warning"
  | "violet";

export interface ChartSeries {
  label: string;
  values: number[];
  tone?: ChartTone;
  tones?: ChartTone[];
}

export interface ChartProps {
  title: string;
  chartType: ChartType;
  labels: string[];
  series: ChartSeries[];
  comparisonBasis?: string;
  dataKind?: ChartDataKind;
  dataSource?: string;
  description?: string;
  unit?: string;
  valueSuffix?: string;
  yMin?: number;
  yMax?: number;
  showLegend?: boolean;
}

const WIDTH = 760;
const HEIGHT = 400;
const PLOT_LEFT = 72;
const PLOT_RIGHT = 24;
const PLOT_TOP = 28;
const PLOT_BOTTOM = 70;
const PLOT_WIDTH = WIDTH - PLOT_LEFT - PLOT_RIGHT;
const PLOT_HEIGHT = HEIGHT - PLOT_TOP - PLOT_BOTTOM;
const TICK_COUNT = 5;

function formatValue(value: number, suffix: string): string {
  const normalized = Math.abs(value) < 0.000_000_1 ? 0 : value;
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(normalized)}${suffix}`;
}

function displayLabel(label: string): string {
  return label.length > 18 ? `${label.slice(0, 17)}…` : label;
}

function niceStep(range: number): number {
  const roughStep = range / (TICK_COUNT - 1);
  const magnitude = 10 ** Math.floor(Math.log10(Math.max(roughStep, Number.EPSILON)));
  const normalized = roughStep / magnitude;
  const multiplier = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return multiplier * magnitude;
}

function roundTick(value: number): number {
  return Number(value.toPrecision(12));
}

const DEFAULT_TONES: readonly ChartTone[] = [
  "coral",
  "secondary",
  "success",
  "warning",
  "violet",
  "accent",
];

function seriesTone(series: ChartSeries, index: number): ChartTone {
  return series.tone ?? DEFAULT_TONES[index % DEFAULT_TONES.length]!;
}

function barTone(
  item: ChartSeries,
  labelIndex: number,
  seriesIndex: number,
  seriesCount: number,
  labelCount: number,
): ChartTone {
  const explicitTone = item.tones?.[labelIndex];
  if (explicitTone) return explicitTone;
  if (item.tone) return item.tone;
  if (seriesCount === 1 && labelCount <= 4) {
    return DEFAULT_TONES[labelIndex % DEFAULT_TONES.length]!;
  }
  return seriesTone(item, seriesIndex);
}

export function Chart({
  title,
  chartType,
  labels,
  series,
  comparisonBasis,
  dataKind,
  dataSource,
  description,
  unit,
  valueSuffix = "",
  yMin,
  yMax,
  showLegend = true,
}: ChartProps) {
  const values = series.flatMap((item) => item.values).filter(Number.isFinite);
  const observedMinimum = Math.min(0, ...values);
  const observedMaximum = Math.max(0, ...values);
  const rawMinimum = yMin ?? observedMinimum;
  const rawMaximum = yMax ?? observedMaximum;
  const rawRange = Math.max(1, rawMaximum - rawMinimum);
  const tickStep = niceStep(rawRange);
  const minimum = yMin ?? Math.floor(rawMinimum / tickStep) * tickStep;
  const candidateMaximum = yMax ?? Math.ceil(rawMaximum / tickStep) * tickStep;
  const maximum = candidateMaximum > minimum ? candidateMaximum : minimum + tickStep;
  const scaleY = (value: number) =>
    PLOT_TOP + ((maximum - value) / (maximum - minimum)) * PLOT_HEIGHT;
  const baselineY = scaleY(Math.min(maximum, Math.max(minimum, 0)));
  const xForIndex = (index: number) =>
    labels.length === 1
      ? PLOT_LEFT + PLOT_WIDTH / 2
      : PLOT_LEFT + (index / (labels.length - 1)) * PLOT_WIDTH;
  const ticks: Array<{ value: number; y: number }> = [];
  const firstTick = Math.ceil(minimum / tickStep) * tickStep;
  for (let value = firstTick; value <= maximum + tickStep * 0.001; value += tickStep) {
    const rounded = roundTick(value);
    ticks.push({ value: rounded, y: scaleY(rounded) });
  }
  const showValues = series.length <= 2 && labels.length * series.length <= 10;
  const valid =
    labels.length >= 2 &&
    series.length > 0 &&
    series.every(
      (item) =>
        item.values.length === labels.length && item.values.every(Number.isFinite),
    );

  if (!valid) {
    return <p className="ca-chart-error">The chart data is incomplete.</p>;
  }

  return (
    <figure
      aria-label={title}
      className="ca-chart"
      data-chart-type={chartType}
      data-series-count={series.length}
    >
      <header>
        <div className="ca-chart-title">
          <span>
            {chartType} chart
            {dataKind ? ` · ${dataKind.replace("-", " ")}` : ""}
            {unit ? ` · ${unit}` : ""}
          </span>
          <strong>{title}</strong>
          {description ? <p>{description}</p> : null}
        </div>
        {showLegend && series.length > 1 ? (
          <ul aria-label="Chart legend" className="ca-chart-legend">
            {series.map((item, index) => (
              <li data-tone={seriesTone(item, index)} key={item.label}>
                <span aria-hidden="true" />
                {item.label}
              </li>
            ))}
          </ul>
        ) : null}
      </header>
      <svg role="img" viewBox={`0 0 ${WIDTH} ${HEIGHT}`}>
        <title>{title}</title>
        {description ? <desc>{description}</desc> : null}
        <g className="ca-chart-grid">
          {ticks.map((tick) => (
            <g key={tick.y}>
              <line x1={PLOT_LEFT} x2={WIDTH - PLOT_RIGHT} y1={tick.y} y2={tick.y} />
              <text x={PLOT_LEFT - 12} y={tick.y + 4}>
                {formatValue(tick.value, valueSuffix)}
              </text>
            </g>
          ))}
        </g>
        <line
          className="ca-chart-axis"
          x1={PLOT_LEFT}
          x2={WIDTH - PLOT_RIGHT}
          y1={baselineY}
          y2={baselineY}
        />
        {chartType === "bar" ? (
          <g className="ca-chart-bars">
            {labels.flatMap((_, labelIndex) => {
              const groupWidth = PLOT_WIDTH / labels.length;
              const availableWidth = groupWidth * 0.72;
              const barWidth = availableWidth / series.length;
              const groupLeft = PLOT_LEFT + labelIndex * groupWidth + groupWidth * 0.14;
              return series.map((item, seriesIndex) => {
                const value = item.values[labelIndex]!;
                const valueY = scaleY(value);
                const x = groupLeft + seriesIndex * barWidth;
                const y = Math.min(baselineY, valueY);
                const accessibleLabel = `${labels[labelIndex]} · ${item.label}: ${formatValue(value, valueSuffix)}`;
                return (
                  <g
                    data-tone={barTone(
                      item,
                      labelIndex,
                      seriesIndex,
                      series.length,
                      labels.length,
                    )}
                    key={`${seriesIndex}-${labelIndex}`}
                  >
                    <rect
                      aria-label={accessibleLabel}
                      height={Math.max(1, Math.abs(baselineY - valueY))}
                      rx={5}
                      width={Math.max(2, barWidth - 4)}
                      x={x}
                      y={y}
                    >
                      <title>{accessibleLabel}</title>
                    </rect>
                    {showValues ? (
                      <text
                        className="ca-chart-value"
                        textAnchor="middle"
                        x={x + (barWidth - 4) / 2}
                        y={value >= 0 ? y - 10 : y + Math.abs(baselineY - valueY) + 17}
                      >
                        {formatValue(value, valueSuffix)}
                      </text>
                    ) : null}
                  </g>
                );
              });
            })}
          </g>
        ) : (
          <g className="ca-chart-lines">
            {series.map((item, seriesIndex) => {
              const points = item.values.map((value, index) => ({
                value,
                x: xForIndex(index),
                y: scaleY(value),
              }));
              const linePath = points
                .map((point, index) => `${index ? "L" : "M"} ${point.x} ${point.y}`)
                .join(" ");
              const areaPath = `${linePath} L ${points.at(-1)!.x} ${baselineY} L ${points[0]!.x} ${baselineY} Z`;
              const tone = seriesTone(item, seriesIndex);
              return (
                <g data-tone={tone} key={item.label}>
                  {chartType === "area" ? (
                    <path className="ca-chart-area" d={areaPath} />
                  ) : null}
                  <path className="ca-chart-line" d={linePath} />
                  {points.map((point, index) => (
                    <g key={`${seriesIndex}-${index}`}>
                      <circle
                        aria-label={`${labels[index]} · ${item.label}: ${formatValue(point.value, valueSuffix)}`}
                        cx={point.x}
                        cy={point.y}
                        r={4}
                      >
                        <title>
                          {labels[index]} · {item.label}: {formatValue(point.value, valueSuffix)}
                        </title>
                      </circle>
                      {showValues ? (
                        <text
                          className="ca-chart-value"
                          textAnchor="middle"
                          x={point.x}
                          y={point.y - 13 - seriesIndex * 14}
                        >
                          {formatValue(point.value, valueSuffix)}
                        </text>
                      ) : null}
                    </g>
                  ))}
                </g>
              );
            })}
          </g>
        )}
        <g className="ca-chart-labels">
          {labels.map((label, index) => {
            const x =
              chartType === "bar"
                ? PLOT_LEFT + ((index + 0.5) / labels.length) * PLOT_WIDTH
                : xForIndex(index);
            return (
              <text key={index} textAnchor="middle" x={x} y={HEIGHT - 34}>
                <title>{label}</title>
                {displayLabel(label)}
              </text>
            );
          })}
        </g>
      </svg>
      {comparisonBasis || dataSource ? (
        <footer className="ca-chart-meta">
          {comparisonBasis ? <p>{comparisonBasis}</p> : null}
          {dataSource ? <cite>Source · {dataSource}</cite> : null}
        </footer>
      ) : null}
      <table className="ca-visually-hidden">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th>Category</th>
            {series.map((item, index) => (
              <th key={index}>{item.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {labels.map((label, index) => (
            <tr key={index}>
              <th>{label}</th>
              {series.map((item, seriesIndex) => (
                <td key={seriesIndex}>
                  {formatValue(item.values[index]!, valueSuffix)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
