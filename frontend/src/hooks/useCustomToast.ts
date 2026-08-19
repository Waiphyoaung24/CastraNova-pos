import { useCallback } from "react"
import { toast } from "sonner"

const useCustomToast = () => {
  const showSuccessToast = useCallback((description: string) => {
    toast.success("Success!", {
      description,
    })
  }, [])

  const showErrorToast = useCallback(
    (description: string, title = "Something went wrong!") => {
      toast.error(title, {
        description,
      })
    },
    [],
  )

  return { showSuccessToast, showErrorToast }
}

export default useCustomToast
