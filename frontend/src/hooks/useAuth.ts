import { useMutation, useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"

import {
  type Body_login_login_access_token as AccessToken,
  LoginService,
  type UserPublic,
  UsersService,
} from "@/client"
import { endSession, markSessionAlive } from "@/lib/auth-session"
import { queryClient } from "@/lib/query-client"
import { handleError } from "@/utils"
import useCustomToast from "./useCustomToast"

const isLoggedIn = () => {
  return localStorage.getItem("access_token") !== null
}

const useAuth = () => {
  const navigate = useNavigate()
  const { showErrorToast } = useCustomToast()

  const { data: user } = useQuery<UserPublic | null, Error>({
    queryKey: ["currentUser"],
    queryFn: UsersService.readUserMe,
    enabled: isLoggedIn(),
  })

  const login = async (data: AccessToken) => {
    const response = await LoginService.loginAccessToken({
      formData: data,
    })
    localStorage.setItem("access_token", response.access_token)
    // A fresh refresh cookie came with that token, so clear the dead-session
    // latch that the previous logout set.
    markSessionAlive()
    // Flush any mutation that was paused (offline) through a prior forced
    // logout — now that we hold a fresh token, it replays with idempotency.
    await queryClient.resumePausedMutations()
  }

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: () => {
      navigate({ to: "/" })
    },
    onError: handleError.bind(showErrorToast),
  })

  const logout = async () => {
    // Clear the httponly refresh cookie server-side so an explicit logout is a
    // true logout (a later refresh can't revive the session); best-effort so an
    // offline/failed call still ends the local session below.
    try {
      await LoginService.logout()
    } catch {
      // ignore — endSession() still clears the local token and redirects
    }
    endSession()
  }

  return {
    loginMutation,
    logout,
    user,
  }
}

export { isLoggedIn }
export default useAuth
