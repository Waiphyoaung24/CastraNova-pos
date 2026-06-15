import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type ExchangeRatesUpdate, SettingsService } from "@/client"
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const formSchema = z.object({
  usd_thb: z
    .string()
    .min(1, { message: "Enter a number" })
    .refine((v) => !Number.isNaN(Number(v)), { message: "Enter a number" })
    .refine((v) => Number(v) >= 0, { message: "Rate cannot be negative" }),
  mmk_thb: z
    .string()
    .min(1, { message: "Enter a number" })
    .refine((v) => !Number.isNaN(Number(v)), { message: "Enter a number" })
    .refine((v) => Number(v) >= 0, { message: "Rate cannot be negative" }),
})

type FormData = z.infer<typeof formSchema>

const ExchangeRates = () => {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()

  const { data, isError } = useQuery({
    queryKey: ["exchange-rates"],
    queryFn: () => SettingsService.getExchangeRates(),
  })

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onSubmit",
    values: {
      usd_thb: data?.usd_thb ?? "0",
      mmk_thb: data?.mmk_thb ?? "0",
    },
  })

  const mutation = useMutation({
    mutationFn: (body: ExchangeRatesUpdate) =>
      SettingsService.updateExchangeRates({ requestBody: body }),
    onSuccess: () => {
      showSuccessToast("Exchange rates updated")
      queryClient.invalidateQueries({ queryKey: ["exchange-rates"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const onSubmit = (values: FormData) => {
    mutation.mutate(values)
  }

  return (
    <div className="max-w-md">
      <h3 className="text-lg font-semibold py-4">Exchange Rates</h3>
      <p className="text-muted-foreground text-sm pb-4">
        THB per 1 unit of the source currency. Used to convert imported supplier
        prices (USD / MMK) into THB.
      </p>
      {isError && (
        <p className="text-sm text-destructive pb-2">
          Could not load the current rates. Refresh to retry before saving.
        </p>
      )}
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex flex-col gap-4"
        >
          <FormField
            control={form.control}
            name="usd_thb"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>USD → THB</FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    step="0.0001"
                    min="0"
                    inputMode="decimal"
                    data-testid="usd-thb-input"
                    aria-invalid={fieldState.invalid}
                    {...field}
                  />
                </FormControl>
                <FormDescription>
                  THB per 1 USD — e.g. 1 USD = 33 THB
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="mmk_thb"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>MMK → THB</FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    step="0.0001"
                    min="0"
                    inputMode="decimal"
                    data-testid="mmk-thb-input"
                    aria-invalid={fieldState.invalid}
                    {...field}
                  />
                </FormControl>
                <FormDescription>
                  THB per 1 MMK — if 1 THB = 132.5 MMK, enter 0.0075
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <LoadingButton
            type="submit"
            loading={mutation.isPending}
            disabled={!data}
            className="self-start"
          >
            Save Rates
          </LoadingButton>
        </form>
      </Form>
    </div>
  )
}

export default ExchangeRates
