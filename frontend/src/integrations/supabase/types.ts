export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.1"
  }
  public: {
    Tables: {
      analysis_runs: {
        Row: {
          context_snapshot: Json | null
          created_at: string
          errors: Json | null
          games_found: number | null
          id: string
          markets_found: number | null
          opportunities_found: number | null
          run_logs: Json | null
          status: string
          total_staked: number | null
          trades_placed: number | null
        }
        Insert: {
          context_snapshot?: Json | null
          created_at?: string
          errors?: Json | null
          games_found?: number | null
          id?: string
          markets_found?: number | null
          opportunities_found?: number | null
          run_logs?: Json | null
          status?: string
          total_staked?: number | null
          trades_placed?: number | null
        }
        Update: {
          context_snapshot?: Json | null
          created_at?: string
          errors?: Json | null
          games_found?: number | null
          id?: string
          markets_found?: number | null
          opportunities_found?: number | null
          run_logs?: Json | null
          status?: string
          total_staked?: number | null
          trades_placed?: number | null
        }
        Relationships: []
      }
      market_prices: {
        Row: {
          captured_at: string
          id: string
          price_no: number | null
          price_yes: number
          run_id: string | null
          ticker: string
          title: string | null
          volume: number | null
        }
        Insert: {
          captured_at?: string
          id?: string
          price_no?: number | null
          price_yes: number
          run_id?: string | null
          ticker: string
          title?: string | null
          volume?: number | null
        }
        Update: {
          captured_at?: string
          id?: string
          price_no?: number | null
          price_yes?: number
          run_id?: string | null
          ticker?: string
          title?: string | null
          volume?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "market_prices_run_id_fkey"
            columns: ["run_id"]
            isOneToOne: false
            referencedRelation: "analysis_runs"
            referencedColumns: ["id"]
          },
        ]
      }
      model_notes: {
        Row: {
          content: string
          created_at: string
          id: string
          updated_at: string
        }
        Insert: {
          content: string
          created_at?: string
          id?: string
          updated_at?: string
        }
        Update: {
          content?: string
          created_at?: string
          id?: string
          updated_at?: string
        }
        Relationships: []
      }
      opportunities: {
        Row: {
          ai_probability: number | null
          bet_placed: boolean | null
          category: string | null
          confidence: number | null
          created_at: string | null
          divergence: number | null
          edge_source: string | null
          expected_value: number | null
          game_scheduled_at: string | null
          id: string
          kalshi_price_at_identification: number | null
          reasoning: string | null
          sharp_implied_probability: number | null
          side: string | null
          ticker: string
          title: string | null
        }
        Insert: {
          ai_probability?: number | null
          bet_placed?: boolean | null
          category?: string | null
          confidence?: number | null
          created_at?: string | null
          divergence?: number | null
          edge_source?: string | null
          expected_value?: number | null
          game_scheduled_at?: string | null
          id?: string
          kalshi_price_at_identification?: number | null
          reasoning?: string | null
          sharp_implied_probability?: number | null
          side?: string | null
          ticker: string
          title?: string | null
        }
        Update: {
          ai_probability?: number | null
          bet_placed?: boolean | null
          category?: string | null
          confidence?: number | null
          created_at?: string | null
          divergence?: number | null
          edge_source?: string | null
          expected_value?: number | null
          game_scheduled_at?: string | null
          id?: string
          kalshi_price_at_identification?: number | null
          reasoning?: string | null
          sharp_implied_probability?: number | null
          side?: string | null
          ticker?: string
          title?: string | null
        }
        Relationships: []
      }
      player_status_cache: {
        Row: {
          created_at: string
          id: string
          injury_description: string | null
          last_checked_at: string
          player_id: string
          player_name: string
          status: string
          team: string
        }
        Insert: {
          created_at?: string
          id?: string
          injury_description?: string | null
          last_checked_at?: string
          player_id: string
          player_name: string
          status: string
          team: string
        }
        Update: {
          created_at?: string
          id?: string
          injury_description?: string | null
          last_checked_at?: string
          player_id?: string
          player_name?: string
          status?: string
          team?: string
        }
        Relationships: []
      }
      settings: {
        Row: {
          id: string
          key: string
          updated_at: string
          value: string
        }
        Insert: {
          id?: string
          key: string
          updated_at?: string
          value: string
        }
        Update: {
          id?: string
          key?: string
          updated_at?: string
          value?: string
        }
        Relationships: []
      }
      trades: {
        Row: {
          closing_price_at_tipoff: number | null
          clv: number | null
          confidence: number | null
          contracts: number | null
          created_at: string
          entry_price: number | null
          environment: string | null
          error_message: string | null
          exit_price: number | null
          exit_reason: string | null
          expected_value: number | null
          game_scheduled_at: string | null
          id: string
          limit_cents: number | null
          opportunity_id: string | null
          order_id: string | null
          peak_price: number | null
          pnl: number | null
          reasoning: string | null
          side: string | null
          stake: number | null
          status: string | null
          ticker: string
          title: string | null
        }
        Insert: {
          closing_price_at_tipoff?: number | null
          clv?: number | null
          confidence?: number | null
          contracts?: number | null
          created_at?: string
          entry_price?: number | null
          environment?: string | null
          error_message?: string | null
          exit_price?: number | null
          exit_reason?: string | null
          expected_value?: number | null
          game_scheduled_at?: string | null
          id?: string
          limit_cents?: number | null
          opportunity_id?: string | null
          order_id?: string | null
          peak_price?: number | null
          pnl?: number | null
          reasoning?: string | null
          side?: string | null
          stake?: number | null
          status?: string | null
          ticker: string
          title?: string | null
        }
        Update: {
          closing_price_at_tipoff?: number | null
          clv?: number | null
          confidence?: number | null
          contracts?: number | null
          created_at?: string
          entry_price?: number | null
          environment?: string | null
          error_message?: string | null
          exit_price?: number | null
          exit_reason?: string | null
          expected_value?: number | null
          game_scheduled_at?: string | null
          id?: string
          limit_cents?: number | null
          opportunity_id?: string | null
          order_id?: string | null
          peak_price?: number | null
          pnl?: number | null
          reasoning?: string | null
          side?: string | null
          stake?: number | null
          status?: string | null
          ticker?: string
          title?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "trades_opportunity_id_fkey"
            columns: ["opportunity_id"]
            isOneToOne: false
            referencedRelation: "opportunities"
            referencedColumns: ["id"]
          },
        ]
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      [_ in never]: never
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
