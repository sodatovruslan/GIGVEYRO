import { SecuritySettingsPage } from "@/components/security/security-settings-page";
import { StoreSettingsPanel } from "@/components/merchant/store-settings-panel";

export default function MerchantSettingsPage() {
  return <>
    <SecuritySettingsPage />
    <StoreSettingsPanel />
  </>;
}
