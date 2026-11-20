import type { ConversationResponse, ConversationSummary, Source, SourceResponse } from './types';

export const sources: Source[] = [
  {
    label: 'S1', chunkId: 'network-isolation', title: 'Platform architecture',
    headingPath: 'Networking / Inference isolation', score: 0.91,
  },
  {
    label: 'S2', chunkId: 'network-policies', title: 'Kubernetes documentation',
    headingPath: 'Services, Load Balancing, and Networking / Network Policies', score: 0.84,
  },
];

export const passages: Record<string, SourceResponse> = {
  'network-isolation': {
    chunkId: 'network-isolation', documentTitle: 'Platform architecture',
    headingPath: 'Networking / Inference isolation',
    text: 'The inference namespace denies ingress and egress by default. Separate policies allow DNS and traffic from approved callers. Selected workloads can reach the GKE metadata server and the private Google API address range. General internet egress is not allowed.\n\nCloud NAT provides an outbound path for private nodes, but it does not filter destinations. Pod network policies provide the workload-level restrictions. Pod egress policies do not govern node image pulls.\n\nThis is a synthetic passage for the frontend demo, based on the platform architecture. It is not a live retrieval result.',
    sourceUrl: 'https://docs.cloud.google.com/kubernetes-engine/docs/how-to/network-policy',
    license: 'Synthetic demo fixture', attribution: 'Platform Assistant demo. Adapted from the local platform architecture; the link provides related GKE documentation.',
  },
  'network-policies': {
    chunkId: 'network-policies', documentTitle: 'Kubernetes documentation',
    headingPath: 'Services, Load Balancing, and Networking / Network Policies',
    text: 'A NetworkPolicy selects a set of Pods and describes allowed connections. Policies are additive: permitted traffic is the union of the applicable rules.\n\nFor a connection between isolated Pods to work, the source egress rules and destination ingress rules must both allow it. A default-deny policy provides the starting point for explicit allowances.\n\nThis passage is an original summary for the demo, not a verbatim extract from the Kubernetes documentation.',
    sourceUrl: 'https://kubernetes.io/docs/concepts/services-networking/network-policies/',
    license: 'Original demo summary; linked Kubernetes documentation: CC BY 4.0',
    attribution: 'Platform Assistant demo; reference: Kubernetes Authors.',
  },
  'health-probes': {
    chunkId: 'health-probes', documentTitle: 'Kubernetes documentation',
    headingPath: 'Workloads / Pod lifecycle / Container probes',
    text: 'When a liveness probe reaches its configured failure threshold, the kubelet restarts that container, subject to its restart policy. A readiness failure instead marks the Pod as not ready so it is removed from normal Service traffic.\n\nA startup probe can protect a slow-starting container: readiness and liveness probes wait until startup succeeds.\n\nThis passage is an original summary for the frontend demo.',
    sourceUrl: 'https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#container-probes',
    license: 'Original demo summary; linked Kubernetes documentation: CC BY 4.0',
    attribution: 'Platform Assistant demo; reference: Kubernetes Authors.',
  },
};

export const probeSources: Source[] = [{
  label: 'S1', chunkId: 'health-probes', title: 'Kubernetes documentation',
  headingPath: 'Workloads / Pod lifecycle / Container probes', score: 0.94,
}];

export const networkAnswer = 'The platform limits a model server’s outbound connections with Kubernetes NetworkPolicy.\n\n1. Start with default-deny egress in the inference namespace.\n2. Allow DNS and the specific identity and Google API endpoints the workload needs.\n3. Keep general internet access closed. [S1]\n\nCloud NAT gives private nodes a route out, but it does not decide which destinations a Pod may reach. The network policies make that decision. Their allow rules are additive, so review every policy selecting the workload. [S2]\n\nThis answer uses demo documentation. Open a source below to inspect the passage.';

export const probeAnswer = 'When a liveness probe fails enough times to reach its failure threshold, the kubelet restarts the container, subject to its restart policy. [S1]\n\nA readiness failure has a different effect: the Pod stops receiving normal Service traffic while it is not ready. It does not trigger a container restart by itself.\n\nUse a startup probe for a slow-starting process so liveness checks do not interrupt initialization. [S1]';

export function seedConversations(): { summaries: ConversationSummary[]; conversations: ConversationResponse[] } {
  return {
    summaries: [
      { id: 'conversation-network', title: 'Keeping inference traffic private', updatedAt: '2026-11-19T15:30:00Z' },
      { id: 'conversation-health', title: 'Liveness and readiness probes', updatedAt: '2026-11-18T10:00:00Z' },
    ],
    conversations: [
      { id: 'conversation-network', title: 'Keeping inference traffic private', messages: [
        { role: 'user', content: 'How does the platform stop a model server from reaching the internet?', status: 'complete', sources: [] },
        { role: 'assistant', content: networkAnswer, status: 'complete', sources },
      ] },
      { id: 'conversation-health', title: 'Liveness and readiness probes', messages: [
        { role: 'user', content: 'What happens when a liveness probe fails?', status: 'complete', sources: [] },
        { role: 'assistant', content: probeAnswer, status: 'complete', sources: probeSources },
      ] },
    ],
  };
}
