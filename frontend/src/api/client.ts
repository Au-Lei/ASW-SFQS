import type {
  BootstrapResponse,
  ErrorResponse,
  SessionResponse,
} from '../../../contracts/generated/contracts';

export class ApiError extends Error {
  constructor(
    message: string,
    public requestId?: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...init,
      credentials: 'same-origin',
      cache: 'no-store',
    });
  } catch {
    throw new ApiError('暂时无法连接本机服务，请确认服务已启动。');
  }
  const requestId = response.headers.get('X-Request-ID') ?? undefined;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = body as ErrorResponse | null;
    throw new ApiError(error?.error?.message ?? '服务返回异常，请稍后重试。', requestId);
  }
  if (body === null) throw new ApiError('服务返回的内容无法读取，请重新检查连接。', requestId);
  return body as T;
}

// Types are generated from the same server contract, never independently redefined here.
let bootstrapInFlight: Promise<BootstrapResponse> | null = null;
export const loadWorkspace = () => {
  // React StrictMode may subscribe twice; avoid racing two initial session cookies.
  bootstrapInFlight ??= request<BootstrapResponse>('/bootstrap').finally(() => {
    bootstrapInFlight = null;
  });
  return bootstrapInFlight;
};
export const verifySession = (token: string) =>
  request<SessionResponse>('/session/verify', {
    method: 'POST',
    headers: { 'X-CSRF-Token': token, 'Content-Type': 'application/json' },
    body: '{}',
  });
