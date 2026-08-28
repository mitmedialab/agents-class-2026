import { useEffect, useState } from "react";

type Point = readonly [number, number];

const VIEWBOX_CENTER = 360;
const CONTOUR_COUNT = 13;
const POINT_COUNT = 72;
const MORPH_DURATION_SECONDS = 8.4;

const HALO: readonly Point[] = Array.from({ length: 18 }, (_, index) => {
  const angle = (Math.PI * 2 * index) / 18 - Math.PI / 2;
  const radius = index % 2 === 0 ? 278 : 248;
  return [
    VIEWBOX_CENTER + Math.cos(angle) * radius,
    VIEWBOX_CENTER + Math.sin(angle) * radius,
  ] as const;
});

const HAND: readonly Point[] = [
  [286, 650],
  [256, 606],
  [236, 548],
  [174, 432],
  [148, 345],
  [156, 316],
  [176, 309],
  [196, 324],
  [278, 436],
  [231, 244],
  [237, 215],
  [255, 203],
  [276, 216],
  [316, 399],
  [298, 164],
  [308, 137],
  [329, 129],
  [348, 148],
  [360, 391],
  [373, 181],
  [390, 160],
  [410, 164],
  [423, 187],
  [414, 409],
  [456, 304],
  [476, 291],
  [496, 300],
  [506, 325],
  [461, 459],
  [458, 522],
  [432, 604],
  [402, 650],
  [350, 665],
];

const BUTTERFLY: readonly Point[] = [
  [360, 307],
  [317, 214],
  [268, 127],
  [229, 91],
  [204, 104],
  [205, 177],
  [132, 135],
  [94, 146],
  [111, 229],
  [72, 259],
  [102, 337],
  [192, 375],
  [118, 453],
  [126, 502],
  [228, 479],
  [305, 419],
  [332, 500],
  [360, 625],
  [388, 500],
  [415, 419],
  [492, 479],
  [594, 502],
  [602, 453],
  [528, 375],
  [618, 337],
  [648, 259],
  [609, 229],
  [626, 146],
  [588, 135],
  [515, 177],
  [516, 104],
  [491, 91],
  [452, 127],
  [403, 214],
];

function resampleClosedPath(points: readonly Point[], sampleCount: number): Point[] {
  const segmentLengths = points.map((point, index) => {
    const next = points[(index + 1) % points.length]!;
    return Math.hypot(next[0] - point[0], next[1] - point[1]);
  });
  const perimeter = segmentLengths.reduce((total, length) => total + length, 0);
  const samples: Point[] = [];
  let segmentIndex = 0;
  let segmentStart = 0;

  for (let index = 0; index < sampleCount; index += 1) {
    const target = (perimeter * index) / sampleCount;
    while (
      segmentIndex < segmentLengths.length - 1 &&
      segmentStart + segmentLengths[segmentIndex]! < target
    ) {
      segmentStart += segmentLengths[segmentIndex]!;
      segmentIndex += 1;
    }
    const start = points[segmentIndex]!;
    const end = points[(segmentIndex + 1) % points.length]!;
    const progress = (target - segmentStart) / segmentLengths[segmentIndex]!;
    samples.push([
      start[0] + (end[0] - start[0]) * progress,
      start[1] + (end[1] - start[1]) * progress,
    ]);
  }

  return samples;
}

function pointString(points: readonly Point[]): string {
  return points
    .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");
}

const MORPH_SHAPES = [HALO, HAND, BUTTERFLY].map((shape) =>
  pointString(resampleClosedPath(shape, POINT_COUNT)),
);
const MORPH_VALUES = [
  MORPH_SHAPES[0],
  MORPH_SHAPES[1],
  MORPH_SHAPES[2],
  MORPH_SHAPES[0],
].join(";");

function useReducedMotion(): boolean {
  const [reducedMotion, setReducedMotion] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updatePreference = () => setReducedMotion(mediaQuery.matches);
    mediaQuery.addEventListener("change", updatePreference);
    return () => mediaQuery.removeEventListener("change", updatePreference);
  }, []);

  return reducedMotion;
}

export interface MorphingLineFigureProps {
  active: boolean;
}

export function MorphingLineFigure({ active }: MorphingLineFigureProps) {
  const reducedMotion = useReducedMotion();

  return (
    <div
      aria-hidden="true"
      className="morphing-line-figure"
      data-active={active}
      data-testid="morphing-line-figure"
    >
      <svg focusable="false" viewBox="0 0 720 720">
        <g className="morphing-line-contours">
          {Array.from({ length: CONTOUR_COUNT }, (_, index) => {
            const offset = index - (CONTOUR_COUNT - 1) / 2;
            const scale = 0.88 + index * 0.02;
            const transform =
              `translate(${VIEWBOX_CENTER} ${VIEWBOX_CENTER}) ` +
              `rotate(${(offset * 2.2).toFixed(1)}) scale(${scale.toFixed(2)}) ` +
              `translate(${-VIEWBOX_CENTER} ${-VIEWBOX_CENTER})`;
            const dashPattern =
              index % 5 === 0 ? "2 8" : index % 4 === 0 ? "6 7" : undefined;

            return (
              <polygon
                className="morphing-line-contour"
                key={`contour-${index}`}
                points={MORPH_SHAPES[0]}
                strokeDasharray={dashPattern}
                strokeWidth={index === 6 ? 1.25 : 0.85}
                transform={transform}
              >
                {active && !reducedMotion ? (
                  <animate
                    attributeName="points"
                    begin={`${(-index * 0.055).toFixed(3)}s`}
                    calcMode="spline"
                    dur={`${MORPH_DURATION_SECONDS}s`}
                    keySplines="0.76 0 0.24 1;0.76 0 0.24 1;0.76 0 0.24 1"
                    keyTimes="0;0.34;0.67;1"
                    repeatCount="indefinite"
                    values={MORPH_VALUES}
                  />
                ) : null}
              </polygon>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
