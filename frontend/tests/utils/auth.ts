import { LoginService, OpenAPI } from "../../src/client"

/** Obtain a fresh access token for the given creds (Node-side SDK calls). */
export async function tokenFor(
  username: string,
  password: string,
): Promise<string> {
  const resp = await LoginService.loginAccessToken({
    formData: { username, password },
  })
  return resp.access_token
}

/** Run an SDK call under a different token, restoring the prior token after. */
export async function withToken<T>(
  token: string,
  fn: () => Promise<T>,
): Promise<T> {
  const saved = OpenAPI.TOKEN
  OpenAPI.TOKEN = token
  try {
    return await fn()
  } finally {
    OpenAPI.TOKEN = saved
  }
}
