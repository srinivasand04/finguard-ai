import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'

export interface GNode {
  id: string; customer_id: string; name: string | null; segment: string; country: string
  risk_level: string | null; pagerank_percentile: number | null; network_id: number | null
  cycle_count: number; chain_count: number; focus: boolean
}
export interface GEdge {
  id: string; source: string; target: string; tx_count: number; total_amount: number
  high_risk_count: number; max_risk_score: number; is_cross_border: boolean; highlight: boolean
}
export interface GraphData { nodes: GNode[]; edges: GEdge[] }

const RISK_COLOR: Record<string, string> = { HIGH: '#dc2626', MEDIUM: '#f59e0b', LOW: '#10b981' }

/** Force-directed money-flow graph. Node colour = customer risk, size = PageRank, edge width = value. */
export default function GraphView({ data, onSelect, height = 520 }: { data: GraphData; onSelect?: (id: string) => void; height?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const maxAmt = Math.max(...data.edges.map(e => e.total_amount), 1)
    const cy = cytoscape({
      container: ref.current,
      elements: [
        ...data.nodes.map(n => ({ data: { ...n, label: n.id, size: 18 + 30 * (n.pagerank_percentile ?? 0) } })),
        ...data.edges.map(e => ({ data: { ...e, width: 1 + 7 * Math.sqrt(e.total_amount / maxAmt) } })),
      ],
      style: [
        { selector: 'node', style: {
          'background-color': (n: cytoscape.NodeSingular) => RISK_COLOR[n.data('risk_level')] ?? '#94a3b8',
          width: 'data(size)', height: 'data(size)', label: 'data(label)', 'font-size': 9, color: '#334155',
          'text-valign': 'bottom', 'text-margin-y': 3, 'border-width': 0,
        } },
        { selector: 'node[?focus]', style: { 'border-width': 4, 'border-color': '#1d4ed8' } },
        { selector: 'node[cycle_count > 0]', style: { shape: 'diamond' } },
        { selector: 'edge', style: {
          width: 'data(width)', 'line-color': '#cbd5e1', 'target-arrow-color': '#cbd5e1', 'target-arrow-shape': 'triangle',
          'curve-style': 'bezier', 'arrow-scale': 0.8, opacity: 0.85,
        } },
        { selector: 'edge[high_risk_count > 0]', style: { 'line-color': '#f87171', 'target-arrow-color': '#f87171' } },
        { selector: 'edge[?highlight]', style: { 'line-color': '#2563eb', 'target-arrow-color': '#2563eb', width: 5, 'z-index': 10 } },
        { selector: ':selected', style: { 'border-width': 4, 'border-color': '#0f172a' } },
      ],
      // Concentric layout: deterministic and O(n) - focus accounts in the centre, then rings by PageRank.
      // (The iterative 'cose' force layout froze hidden/background tabs.)
      layout: {
        name: 'concentric', animate: false, padding: 20, minNodeSpacing: 18,
        concentric: (n: cytoscape.NodeSingular) => (n.data('focus') ? 100 : 0) + 10 * (n.data('pagerank_percentile') ?? 0),
        levelWidth: () => 2,
      } as cytoscape.LayoutOptions,
      wheelSensitivity: 0.3,
    })
    cy.on('tap', 'node', evt => onSelect?.(evt.target.id()))
    cyRef.current = cy
    return () => cy.destroy()
  }, [data, onSelect])

  return <div ref={ref} style={{ height }} className="w-full rounded-lg border border-slate-200 bg-slate-50" />
}

export function GraphLegend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
      <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-red-600" />HIGH-risk customer</span>
      <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-amber-500" />MEDIUM</span>
      <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-emerald-500" />LOW</span>
      <span>◆ in a circular flow</span>
      <span>node size = PageRank</span>
      <span><span className="mr-1 inline-block h-0.5 w-4 bg-red-400 align-middle" />carried a high-risk tx</span>
      <span><span className="mr-1 inline-block h-1 w-4 bg-blue-600 align-middle" />pattern / path hop</span>
      <span>blue ring = focus account</span>
    </div>
  )
}
