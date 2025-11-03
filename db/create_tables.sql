CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS novaims;

CREATE TABLE IF NOT EXISTS novaims.tb_origin_polygons (
    id SERIAL PRIMARY KEY,
    geom geometry(MultiPolygon, 4326),
    "name" varchar(200),
    description varchar(255)
);

CREATE INDEX IF NOT EXISTS sidx_tb_origin_polygons_geom
ON novaims.tb_origin_polygons
USING gist (geom);

DO $$
DECLARE
    minx DOUBLE PRECISION := 8.95;
    miny DOUBLE PRECISION := 48.45;
    maxx DOUBLE PRECISION := 9.15;
    maxy DOUBLE PRECISION := 48.60;



    cell_size_deg DOUBLE PRECISION := 0.01;

    x_steps INTEGER;
    y_steps INTEGER;

    xi INTEGER;
    yi INTEGER;

    x0 DOUBLE PRECISION;
    y0 DOUBLE PRECISION;
    x1 DOUBLE PRECISION;
    y1 DOUBLE PRECISION;
BEGIN
    EXECUTE '
        CREATE TABLE IF NOT EXISTS novaims.tb_boundary_grid (
            id SERIAL PRIMARY KEY,
            "left" DOUBLE PRECISION,
            "right" DOUBLE PRECISION,
            top DOUBLE PRECISION,
            bottom DOUBLE PRECISION,
            geom geometry(Polygon, 4326)
        );
    ';

    IF NOT EXISTS (SELECT 1 FROM novaims.tb_boundary_grid LIMIT 1) THEN

        x_steps := CEIL( (maxx - minx) / cell_size_deg )::INTEGER;
        y_steps := CEIL( (maxy - miny) / cell_size_deg )::INTEGER;

        FOR xi IN 0..x_steps-1 LOOP
            FOR yi IN 0..y_steps-1 LOOP
                x0 := minx + (xi * cell_size_deg);
                x1 := LEAST(x0 + cell_size_deg, maxx);

                y0 := miny + (yi * cell_size_deg);
                y1 := LEAST(y0 + cell_size_deg, maxy);

                INSERT INTO novaims.tb_boundary_grid("left","right",top,bottom,geom)
                VALUES (
                    x0,
                    x1,
                    y1,
                    y0,
                    ST_SetSRID(
                        ST_MakePolygon(
                            ST_MakeLine(ARRAY[
                                ST_MakePoint(x0, y0),
                                ST_MakePoint(x1, y0),
                                ST_MakePoint(x1, y1),
                                ST_MakePoint(x0, y1),
                                ST_MakePoint(x0, y0)
                            ])
                        ),
                        4326
                    )::geometry(Polygon, 4326)
                );

            END LOOP;
        END LOOP;
    END IF;
END$$;
