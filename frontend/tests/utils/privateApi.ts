// Note: the `PrivateService` is only available when generating the client
// for local environments
import {
  LoginService,
  OpenAPI,
  PrivateService,
  UsersService,
} from "../../src/client"
import { firstSuperuser, firstSuperuserPassword } from "../config"

OpenAPI.BASE = `${process.env.VITE_API_URL}`

export const createUser = async ({
  email,
  password,
}: {
  email: string
  password: string
}) => {
  return await PrivateService.createUser({
    requestBody: {
      email,
      password,
      is_verified: true,
      full_name: "Test User",
    },
  })
}

/**
 * Create a non-admin staff user (YGN_STAFF role) via the superuser API.
 * Required because PrivateService.createUser inherits the default BKK_ADMIN
 * role and cannot override it — only the admin endpoint accepts a role field.
 */
export const createStaffUser = async ({
  email,
  password,
}: {
  email: string
  password: string
}) => {
  // Obtain a superuser token for this Node.js-side call
  const tokenResp = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  const savedToken = OpenAPI.TOKEN
  OpenAPI.TOKEN = tokenResp.access_token
  try {
    return await UsersService.createUser({
      requestBody: {
        email,
        password,
        full_name: "Staff User",
        role: "YGN_STAFF",
      },
    })
  } finally {
    OpenAPI.TOKEN = savedToken
  }
}
