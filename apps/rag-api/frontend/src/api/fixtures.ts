import type { ConversationResponse, ConversationSummary, Source } from './types';

export const sources: Source[] = [
  {
    label: 'S1', chunkId: 'network-isolation', title: 'Platform architecture',
    headingPath: 'Networking > Inference isolation', score: 0.91,
    url: 'https://docs.cloud.google.com/kubernetes-engine/docs/how-to/network-policy',
  },
  {
    label: 'S2', chunkId: 'network-policies', title: 'Network Policies',
    headingPath: 'The two sorts of Pod isolation', score: 0.84,
    url: 'https://kubernetes.io/docs/concepts/services-networking/network-policies/#the-two-sorts-of-pod-isolation',
  },
  {
    label: 'S3', chunkId: 'network-policies-2', title: 'Network Policies',
    headingPath: 'Default policies', score: 0.8,
    url: 'https://kubernetes.io/docs/concepts/services-networking/network-policies/#default-policies',
  },
];

export const probeSources: Source[] = [{
  label: 'S1', chunkId: 'health-probes', title: 'Pod Lifecycle',
  headingPath: 'Container probes', score: 0.94,
  url: 'https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#container-probes',
}];

export const networkAnswer = 'The platform limits a model server’s outbound connections with Kubernetes NetworkPolicy [S1].\n\n1. Start with default-deny egress in the inference namespace [S3].\n2. Allow DNS and the specific identity and Google API endpoints the workload needs.\n3. Keep general internet access closed [S1].\n\nA default-deny egress policy looks like this:\n\n```yaml\napiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: default-deny-egress\nspec:\n  podSelector: {}\n  policyTypes:\n    - Egress\n```\n\nAllow rules are additive, so review every policy that selects the workload [S2].';

export const probeAnswer = 'When a liveness probe reaches its failure threshold, the kubelet restarts the container, subject to its restart policy [S1].\n\nA readiness failure has a different effect: the Pod stops receiving Service traffic while it is not ready. Check probe results with `kubectl describe pod <name>`.';

export const generalAnswer = 'Hello! I answer questions about this platform and about Kubernetes, using the team’s documentation. Try asking how a Deployment rolls out a new version.';

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
