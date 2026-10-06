def get_backtest_data(
    symbol,
    interval,
    days=90
):
    """
    Fetch historical data in date chunks.
    Twelve Data allows a maximum of 5000 records
    per request, so 15M 90-day data is fetched
    in smaller chunks.
    """
    try:
        end_date = pd.Timestamp.utcnow().tz_localize(None)
        start_date = (
            end_date
            - pd.Timedelta(days=days)
        )
        # Chunk size chosen to stay comfortably
        # below the 5000-record limit.
        chunk_days = {
            "15min": 25,
            "1h": 60,
            "4h": 90,
        }[interval]
        all_parts = []
        current_start = start_date
        while current_start < end_date:
            current_end = min(
                current_start
                + pd.Timedelta(
                    days=chunk_days
                ),
                end_date
            )
            url = (
                "https://api.twelvedata.com/"
                "time_series"
            )
            params = {
                "symbol": symbol,
                "interval": interval,
                "start_date": current_start.strftime(
                    "%Y-%m-%dT%H:%M:%S"
                ),
                "end_date": current_end.strftime(
                    "%Y-%m-%dT%H:%M:%S"
                ),
                "apikey": TWELVE_DATA_API_KEY,
                "format": "JSON",
            }
            print(
                f"BACKTEST FETCH "
                f"{symbol} {interval} "
                f"{current_start.date()} "
                f"to {current_end.date()}"
            )
            response = requests.get(
                url,
                params=params,
                timeout=60
            )
            data = response.json()
            # ------------------------------------------------
            # IMPORTANT: show the REAL Twelve Data error
            # ------------------------------------------------
            if "values" not in data:
                print(
                    "TWELVE DATA ERROR:"
                )
                print(data)
                return None
            part = pd.DataFrame(
                data["values"]
            )
            if part.empty:
                print(
                    f"No data returned for "
                    f"{symbol} {interval}"
                )
                current_start = current_end
                continue
            part["datetime"] = pd.to_datetime(
                part["datetime"]
            )
            for col in [
                "open",
                "high",
                "low",
                "close",
            ]:
                if col in part.columns:
                    part[col] = pd.to_numeric(
                        part[col],
                        errors="coerce"
                    )
            part = part.dropna(
                subset=[
                    "datetime",
                    "open",
                    "high",
                    "low",
                    "close",
                ]
            )
            all_parts.append(part)
            current_start = current_end
            # Small delay to reduce API pressure
            time.sleep(1)
        # ----------------------------------------------------
        # Combine all chunks
        # ----------------------------------------------------
        if not all_parts:
            print(
                f"No historical data: "
                f"{symbol} {interval}"
            )
            return None
        df = pd.concat(
            all_parts,
            ignore_index=True
        )
        # Remove duplicate candles
        df = (
            df.drop_duplicates(
                subset=["datetime"]
            )
            .sort_values("datetime")
            .reset_index(drop=True)
        )
        # Remove current incomplete candle
        if len(df) > 2:
            df = df.iloc[:-1].copy()
        print(
            f"BACKTEST DATA OK: "
            f"{symbol} {interval} "
            f"{len(df)} candles"
        )
        return df.reset_index(
            drop=True
        )
    except Exception as e:
        print(
            f"BACKTEST FETCH ERROR "
            f"{symbol} {interval}: {e}"
        )
        return None
