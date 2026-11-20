import type { AssistantApi } from './client';

/** True in the mock build (npm run dev and the Playwright build), false in the real one. */
export const isMock = import.meta.env.VITE_API === 'mock';

/** The mock is loaded only in mock builds, so the production bundle never contains it. */
export async function createAssistantApi(): Promise<AssistantApi> {
  if (isMock) {
    const { MockAssistantApi } = await import('./mock');
    return new MockAssistantApi(new URLSearchParams(window.location.search).get('scenario'));
  }
  const { HttpAssistantApi } = await import('./http');
  return new HttpAssistantApi();
}
