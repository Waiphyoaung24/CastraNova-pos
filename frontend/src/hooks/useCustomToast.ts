import { toast } from "sonner"

const useCustomToast = () => {
  const showSuccessToast = (description: string) => {
    toast.success("Success!", {
      description,
    })
  }

  const showErrorToast = (
    description: string,
    title = "Something went wrong!",
  ) => {
    toast.error(title, {
      description,
    })
  }

  return { showSuccessToast, showErrorToast }
}

export default useCustomToast
