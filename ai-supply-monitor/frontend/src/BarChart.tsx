import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Bar } from "./types";

const berlinTime = new Intl.DateTimeFormat("de-DE", {
  timeZone: "Europe/Berlin",
  hour: "2-digit",
  minute: "2-digit",
});

const toSeconds = (iso: string) => (Date.parse(iso) / 1000) as UTCTimestamp;
const formatTime = (t: Time) => berlinTime.format(new Date((t as UTCTimestamp) * 1000));

interface Series {
  candles: ISeriesApi<"Candlestick">;
  volume: ISeriesApi<"Histogram">;
}

/** Candles plus volume for one listing-day; the time axis is labelled in Frankfurt time. */
export function BarChart({ bars }: { bars: Bar[] }) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<Series | null>(null);

  useEffect(() => {
    if (!container.current) return;
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const grid = dark ? "#2a2d33" : "#eceef1";
    const c = createChart(container.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: dark ? "#c9ccd1" : "#3b3f45",
      },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      timeScale: { timeVisible: true, tickMarkFormatter: formatTime },
      localization: { timeFormatter: formatTime },
    });
    const candles = c.addSeries(CandlestickSeries, {
      upColor: "#1a7f5a",
      downColor: "#c2410c",
      borderVisible: false,
      wickUpColor: "#1a7f5a",
      wickDownColor: "#c2410c",
    });
    const volume = c.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
      color: dark ? "#4b5563" : "#cbd2d9",
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    chart.current = c;
    series.current = { candles, volume };
    return () => {
      c.remove();
      chart.current = null;
      series.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chart.current || !series.current) return;
    series.current.candles.setData(
      bars.map((b) => ({ time: toSeconds(b.time), open: b.open, high: b.high, low: b.low, close: b.close })),
    );
    series.current.volume.setData(bars.map((b) => ({ time: toSeconds(b.time), value: b.volume })));
    chart.current.timeScale().fitContent();
  }, [bars]);

  return <div ref={container} className="chart" />;
}
